"""Put fixtures back into R2 from release archives or a directory (docs/09 §5, docs/11 §7.6).

The disaster path: the bucket lost objects, or holds wrong bytes, and the release archives
(ADR-007) are the copy. It writes to production from bytes that came from somewhere else,
so three rules make it safe to run:

**Every byte is verified against the manifest before it can be written.** An archive part
is fetched from GitHub or read from a local file, so each member is untrusted input until
its hash and length match — the same stance as the carry-forward artifact
(`upload.verify_sources`). A member whose bytes do not match stops the restore.

**A tombstone is never restored.** A fixture removed by a takedown (docs/11 §7.8) can still
sit in an older archive; restoring it would undo the takedown.

**Only this repository's release assets, or local files.** From the network, `--restore`
accepts `https://github.com/<repository>/releases/download/<tag>/<name>.tar` and nothing
else.

Unlike a deploy, restore **attempts** to replace a live object whose hash differs from the
manifest (docs/09 §5): that object is wrong by definition, and putting it right is the
point. Under an intact bucket lock R2 refuses the write, and each refusal is reported with
the ceremony that lifts the lock (docs/11 §7.8). No lock gate applies either: on a fresh
account the lock rules are applied only after the restore (docs/11 §7.6 step 4).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import IO, Any

from loremfile.infra.upload import UNVERIFIABLE

CHUNK = 1024 * 1024
HTTP_OK = 200
#: What follows `…/releases/download/`: one tag segment and one `.tar` asset name.
ASSET_PATH = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\.tar")


class RestoreError(RuntimeError):
    """A source could not be used."""


class Action(StrEnum):
    """Restore's own actions. `upload.Action` has no overwrite, by design, and keeps none."""

    UPLOAD = "upload"
    #: Attempted over a live object whose bytes the manifest disowns; refused under a lock.
    REPLACE = "replace"
    SKIP = "skip"


@dataclass(frozen=True)
class Step:
    key: str
    action: Action
    source: str
    size: int
    reason: str = ""


@dataclass
class Available:
    """Verified bytes, by manifest path, and what was seen but not taken."""

    files: dict[str, Path] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers

    def by_action(self, action: Action) -> list[Step]:
        return [step for step in self.steps if step.action is action]

    def render(self) -> str:
        lines = [f"  {action.value}={len(self.by_action(action))}" for action in Action]
        written = [*self.by_action(Action.UPLOAD), *self.by_action(Action.REPLACE)]
        lines.append(f"  bytes={sum(step.size for step in written):,}")
        lines += [f"  replace {step.key}  {step.reason}" for step in self.by_action(Action.REPLACE)]
        lines += [f"  note    {note}" for note in self.notes]
        lines += [f"  BLOCKED {blocker}" for blocker in self.blockers]
        return "\n".join(lines)


# --- sources ------------------------------------------------------------------------


def release_download_prefix(repository: str) -> str:
    return f"https://github.com/{repository}/releases/download/"


def fetch_source(source: str, *, repository: str, dest: Path) -> Path:
    """A local `.tar` as it is, or a release asset of `repository` downloaded into `dest`.

    The URL is checked before anything is requested. github.com answers a release asset
    with a redirect to its asset host, which `urlopen` follows; the bytes are verified
    member by member afterwards, so the redirect target does not need to be trusted.
    """
    if "://" not in source:
        path = Path(source)
        if path.suffix != ".tar" or not path.is_file():
            raise RestoreError(f"{source}: not a local .tar file")
        return path
    prefix = release_download_prefix(repository)
    rest = source[len(prefix) :]
    if not source.startswith(prefix) or not ASSET_PATH.fullmatch(rest) or ".." in rest:
        raise RestoreError(
            f"{source}: only release archive parts of {repository} are accepted "
            f"({prefix}<tag>/<name>.tar)"
        )
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / source.rsplit("/", 1)[-1]
    if target.exists():
        raise RestoreError(f"{target.name} is named twice")
    try:
        with urllib.request.urlopen(source, timeout=60) as response:  # noqa: S310 - checked above
            if response.status != HTTP_OK:
                raise RestoreError(f"{source}: HTTP {response.status}")
            with target.open("wb") as handle:
                shutil.copyfileobj(response, handle, CHUNK)
    except urllib.error.HTTPError as exc:
        raise RestoreError(f"{source}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RestoreError(f"{source}: {exc}") from exc
    return target


# --- verified bytes ---------------------------------------------------------------


def _mismatch(entry: dict[str, Any], digest: str, length: int) -> str | None:
    if digest == entry["sha256"] and length == int(entry["bytes"]):
        return None
    return (
        f"{entry['path']}: the source holds {length} bytes hashing to {digest[:12]}, but the "
        f"manifest says {entry['bytes']} bytes hashing to {str(entry['sha256'])[:12]}. "
        "Refusing to restore bytes the manifest does not describe."
    )


def _copy_verified(stream: IO[bytes], target: Path, entry: dict[str, Any]) -> str | None:
    digest = hashlib.sha256()
    length = 0
    with target.open("wb") as handle:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
            length += len(chunk)
            handle.write(chunk)
    problem = _mismatch(entry, digest.hexdigest(), length)
    if problem:
        target.unlink()
    return problem


def _sorted_by_status(entries: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    active = {e["path"]: e for e in entries if e.get("status", "active") == "active"}
    removed = {e["path"] for e in entries if e.get("status") == "removed"}
    return active, removed


def extract_verified(
    archives: list[Path],
    entries: list[dict[str, Any]],
    work_dir: Path,
    *,
    only: set[str] | None = None,
) -> Available:
    """Every member that is an active manifest path with the manifest's bytes.

    Members are written to numbered scratch files, never to their own names, so a member
    name cannot choose where it lands. Its name only has to equal a manifest path.
    """
    active, removed = _sorted_by_status(entries)
    found = Available()
    work_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for archive in archives:
        try:
            tar = tarfile.open(archive, "r:")  # noqa: SIM115 - closed by the `with` below
        except (tarfile.TarError, OSError) as exc:
            found.blockers.append(f"{archive.name}: not a readable tar archive ({exc})")
            continue
        with tar:
            for member in tar:
                name = member.name
                if name in removed:
                    found.notes.append(f"{name}: tombstoned in the manifest; never restored")
                    continue
                entry = active.get(name)
                if entry is None:
                    found.notes.append(
                        f"{archive.name}: {name!r} is not an active fixture; ignored"
                    )
                    continue
                if (only is not None and name not in only) or name in found.files:
                    continue
                stream = tar.extractfile(member) if member.isfile() else None
                if stream is None:
                    found.blockers.append(f"{name}: not a regular file in {archive.name}")
                    continue
                target = work_dir / f"{written:06d}"
                written += 1
                problem = _copy_verified(stream, target, entry)
                if problem:
                    found.blockers.append(problem)
                else:
                    found.files[name] = target
    return found


def files_from_dir(
    directory: Path, entries: list[dict[str, Any]], *, only: set[str] | None = None
) -> Available:
    """Fixtures at their manifest paths under `directory`, verified in place.

    For when GitHub is gone too (docs/11 §7.6 step 4). A path that resolves outside the
    directory — a symlink, say — is refused rather than followed.
    """
    root = directory.resolve()
    if not root.is_dir():
        raise RestoreError(f"{directory}: not a directory")
    active, removed = _sorted_by_status(entries)
    found = Available()
    for path in sorted(removed):
        if (root / path).exists():
            found.notes.append(f"{path}: tombstoned in the manifest; never restored")
    for path, entry in sorted(active.items()):
        if only is not None and path not in only:
            continue
        candidate = root / path
        if not candidate.exists():
            continue
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            found.blockers.append(f"{path}: resolves outside {directory} or is not a file")
            continue
        digest = hashlib.sha256()
        length = 0
        with resolved.open("rb") as handle:
            while chunk := handle.read(CHUNK):
                digest.update(chunk)
                length += len(chunk)
        problem = _mismatch(entry, digest.hexdigest(), length)
        if problem:
            found.blockers.append(problem)
        else:
            found.files[path] = resolved
    return found


# --- the plan -----------------------------------------------------------------------


def plan_restore(
    available: Available,
    live: dict[str, str],
    entries_by_path: dict[str, dict[str, Any]],
    *,
    only: set[str] | None = None,
) -> Plan:
    """Upload what is missing, skip what matches, attempt to replace what is wrong."""
    plan = Plan(notes=list(available.notes), blockers=list(available.blockers))
    for key in sorted(available.files):
        entry = entries_by_path[key]
        source, size = str(available.files[key]), int(entry["bytes"])
        stored = live.get(key)
        if stored is None:
            plan.steps.append(Step(key, Action.UPLOAD, source, size, "missing from the bucket"))
        elif stored == entry["sha256"]:
            plan.steps.append(Step(key, Action.SKIP, source, size, "published, hash matches"))
        else:
            shown = "no sha256 metadata" if stored == UNVERIFIABLE else f"live hash {stored[:12]}"
            plan.steps.append(
                Step(
                    key,
                    Action.REPLACE,
                    source,
                    size,
                    f"{shown} != manifest {str(entry['sha256'])[:12]}; the replacement is "
                    "attempted and refused by R2 under an intact bucket lock (docs/11 §7.8)",
                )
            )
    if only:
        lacking = sorted(only - set(available.files))
        if lacking:
            plan.blockers.append(
                f"--only names paths the sources do not hold verified: {', '.join(lacking)}"
            )
    if not available.files and not plan.blockers:
        plan.blockers.append("the sources hold no active fixture of this manifest; nothing to do")
    return plan
