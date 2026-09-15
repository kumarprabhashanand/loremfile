"""Remove a taken-down fixture from the GitHub Release archives (docs/09 §10, ADR-031).

A takedown deletes the object from R2 (docs/11 §7.8), but the bytes also sit in every release
archive that shipped the path. This rebuilds those parts from the released bytes without it,
replaces them in place, and notes the redaction. `sha256sums.txt` and `manifest.json` stay as
released: the recorded hash is the tombstone a restore relies on.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loremfile.infra import release
from loremfile.manifest import Manifest

PART = re.compile(
    r"fixtures-(?P<since>snapshot|v\d+\.\d+\.\d+)-(?P<tag>v\d+\.\d+\.\d+)\.part(?P<number>\d+)\.tar"
)
PARTS_LISTING = "parts.txt"


class RedactError(RuntimeError):
    """A release could not be read or rewritten."""


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("gh")
    if executable is None:
        raise RedactError("gh is not on PATH; it lives in the toolchain image")
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [executable, *args], capture_output=True, text=True, timeout=900, check=False
    )


def _gh(args: list[str]) -> str:
    done = _run(args)
    if done.returncode != 0:
        raise RedactError(f"gh {' '.join(args[:3])}: {done.stderr.strip()}")
    return done.stdout


def immutable_setting(repository: str) -> str:
    """`on`, `off`, or `unreadable (…)`. GITHUB_TOKEN has no administration scope, so a
    refusal to read it is expected; each release's own `isImmutable` still decides."""
    done = _run(["api", f"repos/{repository}/immutable-releases"])
    if done.returncode == 0:
        try:
            return "on" if json.loads(done.stdout or "{}").get("enabled") else "off"
        except ValueError:
            return f"unreadable ({done.stdout.strip()[:80]})"
    if "404" in done.stderr:
        return "off"
    return f"unreadable ({done.stderr.strip() or f'exit {done.returncode}'})"


@dataclass(frozen=True)
class Archive:
    tag: str
    since: str | None
    parts: tuple[str, ...]
    immutable: bool
    notes: str


def archive_of(view: dict[str, Any]) -> Archive | None:
    """The fixture archive a release carries, read from its asset names; None if it has none."""
    tag = str(view["tagName"])
    found: list[tuple[int, str, str]] = []
    for asset in view.get("assets") or []:
        name = str(asset.get("name", ""))
        match = PART.fullmatch(name)
        if match is None:
            continue
        if match["tag"] != tag:
            raise RedactError(f"{tag}: asset {name} belongs to {match['tag']}")
        found.append((int(match["number"]), name, match["since"]))
    if not found:
        return None
    sinces = {since for _, _, since in found}
    if len(sinces) != 1:
        raise RedactError(f"{tag}: parts disagree about what the archive covers: {sorted(sinces)}")
    since = sinces.pop()
    return Archive(
        tag=tag,
        since=None if since == "snapshot" else since,
        parts=tuple(name for _, name, _ in sorted(found)),
        immutable=bool(view.get("isImmutable")),
        notes=str(view.get("body") or ""),
    )


def releases(repository: str) -> list[dict[str, Any]]:
    listed = json.loads(
        _gh(["release", "list", "--repo", repository, "--limit", "1000", "--json", "tagName"])
        or "[]"
    )
    fields = "tagName,assets,isImmutable,body"
    return [
        json.loads(
            _gh(["release", "view", item["tagName"], "--repo", repository, "--json", fields])
        )
        for item in listed
    ]


def members_of(archive: Archive, *, cwd: Path | None) -> list[dict[str, Any]]:
    """What the archive holds, recomputed from git exactly as `release archive` chose it."""
    plan = release.Plan(tag=archive.tag, since=archive.since)
    return release.members(plan, release.manifest_at(archive.tag, cwd=cwd), cwd=cwd)


def rebuild(
    archive: Archive, path: str, *, repository: str, work: Path, cwd: Path | None
) -> list[Path]:
    """The archive's parts and listing without `path`, built from the released bytes.

    `release.build_archive` verifies every member against the manifest again, so a released
    part that no longer matches stops the redaction instead of being republished.
    """
    released = work / "released"
    released.mkdir(parents=True)
    patterns = [flag for name in archive.parts for flag in ("--pattern", name)]
    _gh(
        [
            "release",
            "download",
            archive.tag,
            "--repo",
            repository,
            "--dir",
            str(released),
            *patterns,
        ]
    )
    wanted = [entry for entry in members_of(archive, cwd=cwd) if entry["path"] != path]
    keep = {entry["path"] for entry in wanted}
    extracted = work / "members"
    extracted.mkdir()
    files: dict[str, Path] = {}
    for name in archive.parts:
        with tarfile.open(released / name, "r:") as tar:
            for member in tar:
                if member.name not in keep or member.name in files or not member.isfile():
                    continue
                stream = tar.extractfile(member)
                if stream is None:
                    continue
                target = extracted / f"{len(files):06d}"
                with target.open("wb") as handle:
                    shutil.copyfileobj(stream, handle)
                files[member.name] = target
    lacking = sorted(keep - set(files))
    if lacking:
        raise RedactError(f"{archive.tag}: the released parts lack {', '.join(lacking[:3])}")
    out = work / "rebuilt"
    stem = release.Plan(tag=archive.tag, since=archive.since).stem
    built = release.build_archive(wanted, lambda p: files[p].read_bytes(), out, stem=stem)
    return [*built.parts, out / PARTS_LISTING] if built.parts else []


def publish(
    archive: Archive, rebuilt: list[Path], path: str, *, repository: str, work: Path, today: str
) -> None:
    if rebuilt:
        _gh(
            [
                "release",
                "upload",
                archive.tag,
                "--repo",
                repository,
                "--clobber",
                *map(str, rebuilt),
            ]
        )
    kept = {part.name for part in rebuilt}
    stale = [name for name in archive.parts if name not in kept]
    if not rebuilt:
        stale.append(PARTS_LISTING)
    for name in stale:
        _gh(["release", "delete-asset", archive.tag, name, "--repo", repository, "--yes"])
    notes = work / "notes.md"
    notes.write_text(
        f"{archive.notes.rstrip()}\n\nRedacted `{path}` on {today} (docs/11 §7.8).\n",
        encoding="utf-8",
    )
    _gh(["release", "edit", archive.tag, "--repo", repository, "--notes-file", str(notes)])


@dataclass
class Report:
    setting: str = ""
    scanned: int = 0
    changed: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        if self.setting == "on":
            return [
                *self.problems,
                "immutable releases are enabled for this repository; they must stay off (ADR-031)",
            ]
        return list(self.problems)

    def render(self) -> str:
        lines = [
            f"  immutable-releases setting: {self.setting}",
            f"  releases with an archive: {self.scanned}",
            f"  containing the path: {', '.join(self.changed) or 'none'}",
        ]
        return "\n".join(lines + [f"  REFUSED {problem}" for problem in self.errors])


def redact(
    path: str,
    *,
    repository: str,
    manifest: Manifest,
    cwd: Path | None,
    work: Path,
    dry_run: bool,
    today: str,
) -> Report:
    report = Report(setting=immutable_setting(repository))
    entry = manifest.by_path.get(path)
    if entry is None or entry.get("status") != "removed":
        report.problems.append(
            f"{path} is not a tombstone in manifest.json; "
            "redact only after the takedown (docs/11 §7.8)"
        )
        return report
    for view in releases(repository):
        archive = archive_of(view)
        if archive is None:
            continue
        report.scanned += 1
        if path not in {member["path"] for member in members_of(archive, cwd=cwd)}:
            continue
        if archive.immutable:
            report.problems.append(
                f"{archive.tag} is an immutable release, so its assets cannot be replaced. "
                f"Removing {path} would mean deleting the whole release, losing the restore "
                "archive for every other fixture in it, and never reusing the tag name (ADR-031)."
            )
            continue
        report.changed.append(archive.tag)
        if not dry_run:
            scratch = work / archive.tag
            scratch.mkdir(parents=True)
            rebuilt = rebuild(archive, path, repository=repository, work=scratch, cwd=cwd)
            publish(archive, rebuilt, path, repository=repository, work=scratch, today=today)
    return report
