"""`release redact`: a taken-down fixture leaves every release archive that shipped it."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest

from loremfile.infra import redact, release
from loremfile.infra.release import ReleaseError
from loremfile.manifest import Manifest

REPO = "owner/loremfile"
BODIES = {"pdf/a.pdf": b"%PDF-a", "png/b.png": b"\x89PNG-b", "csv/c.csv": b"x,y\n1,2\n"}


def entry(path: str, **extra: Any) -> dict[str, Any]:
    body = BODIES[path]
    return {
        "path": path,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "status": "active",
        **extra,
    }


def git(repo: Path, *args: str) -> None:
    executable = shutil.which("git")
    assert executable is not None
    subprocess.run(  # noqa: S603 - fixed argv
        [
            executable,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """v1.0.0 ships a and b (snapshot); v1.1.0 adds c (delta)."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    for version, paths in (
        ("1.0.0", ["pdf/a.pdf", "png/b.png"]),
        ("1.1.0", ["pdf/a.pdf", "png/b.png", "csv/c.csv"]),
    ):
        document = {"catalog_version": version, "fixtures": [entry(p) for p in paths]}
        (root / "manifest.json").write_text(json.dumps(document))
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", version)
        git(root, "tag", f"v{version}")
    return root


def tombstoned(path: str) -> Manifest:
    fixtures = [entry(p) for p in BODIES if p != path] + [
        entry(path, status="removed", reason="takedown")
    ]
    return Manifest.from_document({"catalog_version": "1.1.1", "fixtures": fixtures})


VIEWS = {
    "v1.0.0": {
        "tagName": "v1.0.0",
        "isImmutable": False,
        "body": "Release one.",
        "assets": [
            {"name": "fixtures-snapshot-v1.0.0.part1.tar"},
            {"name": "parts.txt"},
            {"name": "manifest.json"},
            {"name": "sha256sums.txt"},
        ],
    },
    "v1.1.0": {
        "tagName": "v1.1.0",
        "isImmutable": False,
        "body": "Release two.",
        "assets": [{"name": "fixtures-v1.0.0-v1.1.0.part1.tar"}, {"name": "parts.txt"}],
    },
}
RELEASED = {"v1.0.0": ["pdf/a.pdf", "png/b.png"], "v1.1.0": ["csv/c.csv"]}


def tampered_part(part: Path, paths: list[str]) -> None:
    """A released part whose `pdf/a.pdf` no longer hashes to the manifest."""
    with tarfile.open(part, "w") as tar:
        for path in paths:
            body = b"%PDF-tampered" if path == "pdf/a.pdf" else BODIES[path]
            info = tarfile.TarInfo(path)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))


class Gh:
    """GitHub, as `gh` answers it: canned views, real tar parts on download, recorded writes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[list[str]] = []
        self.views = json.loads(json.dumps(VIEWS))
        self.uploaded: dict[str, list[str]] = {}
        self.notes: dict[str, str] = {}
        self.tamper = False
        monkeypatch.setattr(redact, "_run", self.run)

    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        out = ""
        # GITHUB_TOKEN cannot read the repository setting (run 34989880279, HTTP 403).
        assert args[0] == "release", f"redact must only call `gh release`, not {args[0]}"
        verb, tag = args[1], (args[2] if len(args) > 2 else "")
        if verb == "list":
            out = json.dumps([{"tagName": t} for t in self.views])
        elif verb == "view":
            out = json.dumps(self.views[tag])
        elif verb == "download":
            directory = Path(args[args.index("--dir") + 1])
            archive = redact.archive_of(self.views[tag])
            assert archive is not None
            if self.tamper:
                tampered_part(directory / archive.parts[0], RELEASED[tag])
            else:
                stem = release.Plan(tag=tag, since=archive.since).stem
                release.build_archive(
                    [entry(p) for p in RELEASED[tag]],
                    BODIES.__getitem__,
                    directory / "built",
                    stem=stem,
                )
                for built in (directory / "built").glob("*.tar"):
                    built.rename(directory / built.name)
        elif verb == "upload":
            files = [Path(a) for a in args[args.index("--clobber") + 1 :]]
            names: list[str] = []
            for file in files:
                if file.suffix == ".tar":
                    with tarfile.open(file) as tar:
                        names += tar.getnames()
            self.uploaded[tag] = [f.name for f in files] + names
        elif verb == "edit":
            self.notes[tag] = Path(args[args.index("--notes-file") + 1]).read_text()
        return subprocess.CompletedProcess(args, 0, out, "")

    def writes(self) -> list[list[str]]:
        return [
            c
            for c in self.calls
            if c[0] == "release" and c[1] in {"upload", "delete-asset", "edit"}
        ]


def run(repo: Path, tmp_path: Path, path: str, *, dry_run: bool = False) -> redact.Report:
    return redact.redact(
        path,
        repository=REPO,
        manifest=tombstoned(path),
        cwd=repo,
        work=tmp_path / "work",
        dry_run=dry_run,
        today="2026-10-01",
    )


def test_only_the_releases_that_shipped_the_path_are_rebuilt(
    monkeypatch: pytest.MonkeyPatch, repo: Path, tmp_path: Path
) -> None:
    gh = Gh(monkeypatch)
    report = run(repo, tmp_path, "png/b.png")
    assert report.errors == []
    assert report.changed == ["v1.0.0"]
    assert gh.uploaded == {
        "v1.0.0": ["fixtures-snapshot-v1.0.0.part1.tar", "parts.txt", "pdf/a.pdf"]
    }
    assert "Redacted `png/b.png` on 2026-10-01" in gh.notes["v1.0.0"]
    assert gh.notes["v1.0.0"].startswith("Release one.")
    assert all(call[2] == "v1.0.0" for call in gh.writes()), "v1.1.0 never shipped the path"
    for call in gh.calls:
        if call[0] == "release":
            assert call[call.index("--repo") + 1] == REPO


def test_an_archive_left_empty_loses_its_parts_and_listing(
    monkeypatch: pytest.MonkeyPatch, repo: Path, tmp_path: Path
) -> None:
    gh = Gh(monkeypatch)
    run(repo, tmp_path, "csv/c.csv")
    deleted = [c[3] for c in gh.writes() if c[1] == "delete-asset"]
    assert deleted == ["fixtures-v1.0.0-v1.1.0.part1.tar", "parts.txt"]
    assert gh.uploaded == {}


def test_an_immutable_release_is_refused_with_its_cost(
    monkeypatch: pytest.MonkeyPatch, repo: Path, tmp_path: Path
) -> None:
    gh = Gh(monkeypatch)
    gh.views["v1.0.0"]["isImmutable"] = True
    report = run(repo, tmp_path, "png/b.png")
    (problem,) = report.errors
    assert "deleting the whole release" in problem and "tag name" in problem
    assert gh.writes() == []


def test_a_dry_run_names_the_releases_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, repo: Path, tmp_path: Path
) -> None:
    gh = Gh(monkeypatch)
    report = run(repo, tmp_path, "png/b.png", dry_run=True)
    assert report.changed == ["v1.0.0"]
    assert gh.writes() == []
    assert not any(c[1] == "download" for c in gh.calls if c[0] == "release")


def test_a_path_that_is_not_a_tombstone_is_refused_before_anything_is_read(
    monkeypatch: pytest.MonkeyPatch, repo: Path, tmp_path: Path
) -> None:
    gh = Gh(monkeypatch)
    report = redact.redact(
        "png/b.png",
        repository=REPO,
        manifest=tombstoned("csv/c.csv"),
        cwd=repo,
        work=tmp_path / "w",
        dry_run=False,
        today="2026-10-01",
    )
    assert "not a tombstone" in report.errors[0]
    assert gh.calls == []


def test_released_bytes_that_no_longer_match_stop_the_redaction(
    monkeypatch: pytest.MonkeyPatch, repo: Path, tmp_path: Path
) -> None:
    gh = Gh(monkeypatch)
    gh.tamper = True
    with pytest.raises(ReleaseError, match="not a restore path"):
        run(repo, tmp_path, "png/b.png")
    assert gh.writes() == []


def test_part_names_decide_what_an_archive_covers() -> None:
    snapshot = redact.archive_of(VIEWS["v1.0.0"])
    delta = redact.archive_of(VIEWS["v1.1.0"])
    assert snapshot is not None and snapshot.since is None
    assert delta is not None and delta.since == "v1.0.0"
    assert redact.archive_of({"tagName": "v1.1.1", "assets": [{"name": "manifest.json"}]}) is None
    with pytest.raises(redact.RedactError, match="belongs to"):
        redact.archive_of(
            {"tagName": "v1.2.0", "assets": [{"name": "fixtures-snapshot-v1.0.0.part1.tar"}]}
        )
