"""Release archives (docs/09 §3.5).

**The bytes come from production, not from a rebuild.** That is the point of the
archive: it is the restore path when the bucket is gone, so an archive assembled from
regenerated fixtures would only prove the generators still run. It has to hold the bytes
that were actually served — which is also why every member is verified against the
manifest hash before it goes in.

Archives split at 1.5 GB into numbered parts with a `parts.txt` listing each part and
its SHA-256, so every asset stays under GitHub's 2 GB limit.

**Rehearsed before it is used.** `release.yml` has a dispatch mode that assembles and
verifies the whole archive from the published bytes and publishes nothing, so the first
exercise of `fetch_published` against production is not also the first public release.
The unit tests drive every function here against fakes and a scratch git repository; a
green suite is not end-to-end verification — the rehearsal is.

**Which tag, which archive.** The previous release is the highest `vX.Y.Z` tag reachable
from the release ref whose version is below the one being released — not `git describe`,
which exits 128 both when there is no tag at all and when something is actually wrong. No
previous release, or a minor version that is a multiple of ten with patch 0, means a full
snapshot; anything else is a delta of the paths the previous release's manifest did not
have (docs/09 §3.5).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loremfile.manifest import Manifest, ManifestError, render_sha256sums

#: GitHub: "Each file included in a release must be under 2 GiB." Split well below it.
PART_LIMIT_BYTES = 1_500_000_000
#: docs/09 §3.5: a full snapshot "for the first release and for every 10th minor release".
SNAPSHOT_EVERY_MINOR = 10
TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
HTTP_OK = 200


class ReleaseError(RuntimeError):
    """An archive could not be assembled, or a member failed verification."""


@dataclass
class Archive:
    parts: list[Path] = field(default_factory=list)
    members: int = 0
    total_bytes: int = 0
    #: sha256 of each part, for parts.txt.
    digests: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        lines = [f"  {self.members} member(s), {self.total_bytes:,} bytes"]
        lines += [f"    {path.name}  {self.digests[path.name][:16]}…" for path in self.parts]
        return "\n".join(lines)


def added_since(
    current: list[dict[str, Any]], previous: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Entries in `current` that the previous release did not have.

    Compared by path only. An entry cannot change its bytes at a published path, so a
    path present in both is byte-identical in both, and shipping it again would only make
    the delta archive larger.
    """
    seen = {entry["path"] for entry in previous}
    return [entry for entry in current if entry["path"] not in seen]


def verify_member(entry: dict[str, Any], data: bytes) -> None:
    """Refuse anything that does not match the manifest. The archive is a restore path."""
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry["sha256"]:
        raise ReleaseError(
            f"{entry['path']}: fetched bytes hash {digest[:12]} but the manifest says "
            f"{entry['sha256'][:12]}. An archive of unverified bytes is not a restore path."
        )
    if len(data) != int(entry["bytes"]):
        raise ReleaseError(f"{entry['path']}: {len(data)} bytes, manifest says {entry['bytes']}")


def build_archive(
    entries: list[dict[str, Any]],
    fetch: Callable[[str], bytes],
    out_dir: Path,
    *,
    stem: str,
    part_limit: int = PART_LIMIT_BYTES,
) -> Archive:
    """Assemble the tar parts. `fetch` returns the **published** bytes for a path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = Archive()
    part_number = 1
    current: tarfile.TarFile | None = None
    current_path: Path | None = None
    current_bytes = 0

    def close() -> None:
        nonlocal current, current_path
        if current is not None and current_path is not None:
            current.close()
            archive.parts.append(current_path)
            archive.digests[current_path.name] = hashlib.sha256(
                current_path.read_bytes()
            ).hexdigest()
            current = None
            current_path = None

    for entry in entries:
        data = fetch(entry["path"])
        verify_member(entry, data)
        if current is None or current_bytes + len(data) > part_limit:
            close()
            current_path = out_dir / f"{stem}.part{part_number}.tar"
            # Not a context manager: a part stays open across loop iterations until it
            # fills, and close() below is the single place every part is finalised.
            current = tarfile.open(current_path, "w")  # noqa: SIM115
            current_bytes = 0
            part_number += 1
        info = tarfile.TarInfo(name=entry["path"])
        info.size = len(data)
        # Fixed metadata: an archive of the same fixtures is the same archive.
        info.mtime = 0
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        current.addfile(info, io.BytesIO(data))
        current_bytes += len(data)
        archive.members += 1
        archive.total_bytes += len(data)
    close()

    if archive.parts:
        listing = "\n".join(f"{archive.digests[path.name]}  {path.name}" for path in archive.parts)
        (out_dir / "parts.txt").write_text(listing + "\n", encoding="utf-8")
    return archive


# --- which release, and against what ------------------------------------------------


@dataclass(frozen=True)
class Plan:
    tag: str
    #: None for a snapshot.
    since: str | None

    @property
    def mode(self) -> str:
        return "snapshot" if self.since is None else "delta"

    @property
    def stem(self) -> str:
        return (
            f"fixtures-snapshot-{self.tag}"
            if self.since is None
            else f"fixtures-{self.since}-{self.tag}"
        )


def version_of(tag: str) -> tuple[int, int, int]:
    match = TAG.fullmatch(tag)
    if match is None:
        raise ReleaseError(f"{tag!r} is not a release tag; release tags are vMAJOR.MINOR.PATCH")
    major, minor, patch = (int(part) for part in match.groups())
    return (major, minor, patch)


def check_tag(tag: str, catalog_version: str) -> None:
    """docs/09 §3.5 step 1: the tag names exactly the version the manifest declares."""
    version_of(tag)
    if tag != f"v{catalog_version}":
        raise ReleaseError(
            f"tag {tag} does not match manifest.json catalog_version {catalog_version}; "
            "tag the commit whose manifest declares that version"
        )


def _git(args: list[str], cwd: Path | None) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("git")
    if executable is None:
        raise ReleaseError("git is not on PATH")
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [executable, *args], cwd=cwd, capture_output=True, text=True, timeout=60, check=False
    )


def previous_tag(ref: str, tag: str, *, cwd: Path | None = None) -> str | None:
    """The highest release tag reachable from `ref` whose version is below `tag`'s.

    `release archive` passes `HEAD`: the tagged commit on a tag push, the dispatched commit
    in a rehearsal. The tag being released is reachable from itself and is excluded by the
    version comparison, so no `<tag>^` is needed — which would fail outright on a root commit.
    """
    current = version_of(tag)
    listed = _git(["tag", "--merged", ref, "--list", "v*"], cwd)
    if listed.returncode != 0:
        raise ReleaseError(f"git tag --merged {ref} failed: {listed.stderr.strip()}")
    earlier = [
        name for name in listed.stdout.split() if TAG.fullmatch(name) and version_of(name) < current
    ]
    return max(earlier, key=version_of) if earlier else None


def plan_release(tag: str, previous: str | None) -> Plan:
    """A snapshot for the first release and for every 10th minor; otherwise a delta."""
    _major, minor, patch = version_of(tag)
    tenth_minor = patch == 0 and minor > 0 and minor % SNAPSHOT_EVERY_MINOR == 0
    if previous is None or tenth_minor:
        return Plan(tag=tag, since=None)
    return Plan(tag=tag, since=previous)


def manifest_at(tag: str, *, cwd: Path | None = None) -> Manifest:
    """The manifest as it was at an earlier release, read from git rather than guessed."""
    shown = _git(["show", f"{tag}:manifest.json"], cwd)
    if shown.returncode != 0:
        raise ReleaseError(f"cannot read manifest.json at {tag}: {shown.stderr.strip()}")
    try:
        return Manifest.from_document(json.loads(shown.stdout), source=f"{tag}:manifest.json")
    except (ValueError, ManifestError) as exc:
        raise ReleaseError(f"manifest.json at {tag} is unreadable: {exc}") from exc


def members(plan: Plan, current: Manifest, *, cwd: Path | None = None) -> list[dict[str, Any]]:
    """What goes in the archive: every active fixture, or those the previous release lacked.

    Tombstones are never members — their objects are gone — and a delta compares against
    every path the previous manifest named, removed ones included."""
    active = sorted(current.active, key=lambda entry: entry["path"])
    if plan.since is None:
        return active
    return added_since(active, manifest_at(plan.since, cwd=cwd).entries)


# --- the published bytes, and the notes ---------------------------------------------


def fetch_published(path: str) -> bytes:
    """The bytes production serves for a fixture, fetched like any client would.

    Through `verify_live.fetch`, which retries only a 429 from our own rate limit. Anything
    but a 200 is an error: tag a release only after the deploy that published it is green
    (docs/09 §7).
    """
    from loremfile.infra import verify_live  # noqa: PLC0415 - keeps this module light to import

    response = verify_live.fetch(f"/{path}", method="GET")
    if response.status != HTTP_OK:
        answer = response.status or "no response"
        raise ReleaseError(
            f"{path}: production answered {answer}. Release archives hold published bytes, so "
            "tag only after the deploy that published this fixture is green (docs/09 §7)."
        )
    return response.body


def changelog_excerpt(changelog: str, version: str) -> str:
    """The `## [version]` section of CHANGELOG.md, without the next section."""
    lines = changelog.splitlines()
    heading = re.compile(rf"^## \[{re.escape(version)}\]")
    starts = [index for index, line in enumerate(lines) if heading.match(line)]
    if not starts:
        raise ReleaseError(
            f"CHANGELOG.md has no `## [{version}]` section; move the released entries out of "
            "[Unreleased] under that heading before tagging"
        )
    body: list[str] = []
    for line in lines[starts[0] + 1 :]:
        if line.startswith("## ["):
            break
        body.append(line)
    text = "\n".join(body).strip()
    if not text:
        raise ReleaseError(f"CHANGELOG.md's `## [{version}]` section is empty")
    return f"{lines[starts[0]]}\n\n{text}\n"


@dataclass
class ReleaseAssets:
    plan: Plan
    archive: Archive
    files: list[Path] = field(default_factory=list)
    #: None when a rehearsal proceeded without the CHANGELOG section.
    notes: Path | None = None


def assemble(
    plan: Plan,
    current: Manifest,
    entries: list[dict[str, Any]],
    *,
    manifest_file: Path,
    changelog: str,
    out_dir: Path,
    fetch: Callable[[str], bytes] = fetch_published,
    rehearsal: bool = False,
) -> ReleaseAssets:
    """Every asset for one release, written to an empty directory.

    The notes are checked first, so a release that could not be published fails before it
    downloads anything; a rehearsal records their absence instead, because it publishes
    nothing. The directory must be empty: `release.yml` attaches everything in it.
    """
    check_tag(plan.tag, current.catalog_version)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ReleaseError(f"{out_dir} is not empty; every file in it would be attached")
    excerpt: str | None = None
    try:
        excerpt = changelog_excerpt(changelog, current.catalog_version)
    except ReleaseError:
        if not rehearsal:
            raise

    archive = build_archive(entries, fetch, out_dir, stem=plan.stem)
    shutil.copyfile(manifest_file, out_dir / "manifest.json")
    (out_dir / "sha256sums.txt").write_text(render_sha256sums(current), encoding="utf-8")
    assets = ReleaseAssets(plan=plan, archive=archive)
    if excerpt is not None:
        assets.notes = out_dir / "notes.md"
        assets.notes.write_text(excerpt, encoding="utf-8")
    assets.files = sorted(path for path in out_dir.iterdir() if path.is_file())
    return assets
