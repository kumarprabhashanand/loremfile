"""`upload --restore`: the disaster path puts back only verified, active fixtures (docs/09 §5).

Restore writes to production from bytes that came from elsewhere — a GitHub release asset
or a local directory — so each way it could publish the wrong thing is pinned here: a
source from another origin, a member whose bytes the manifest does not describe, a
tombstone brought back from an older archive, a name that tries to escape its directory,
and a live object silently skipped or silently written over.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.error
from pathlib import Path
from typing import Any

import pytest
import yaml
from boto3.exceptions import S3UploadFailedError
from click.testing import CliRunner

from loremfile import cli, config
from loremfile.infra import purge, r2, restore
from loremfile.infra.restore import Action, Available, RestoreError
from loremfile.infra.upload import UNVERIFIABLE

INFRA = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "infra.yml"
REPO = "owner/loremfile"
PREFIX = "https://github.com/owner/loremfile/releases/download/"
BODIES = {"pdf/a.pdf": b"%PDF-a", "png/b.png": b"\x89PNG-b"}


def fixture(path: str, body: bytes, **extra: Any) -> dict[str, Any]:
    return {
        "path": path,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "mime": "application/octet-stream",
        "status": "active",
        **extra,
    }


def entries() -> list[dict[str, Any]]:
    removed = fixture("txt/c.txt", b"taken down", status="removed", reason="takedown")
    return [*(fixture(path, body) for path, body in BODIES.items()), removed]


def tar_of(path: Path, members: dict[str, bytes], *, directories: tuple[str, ...] = ()) -> Path:
    with tarfile.open(path, "w") as tar:
        for name in directories:
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE
            tar.addfile(info)
        for name, body in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return path


# --- sources ---------------------------------------------------------------------------


class Opened:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.stream = io.BytesIO(body)
        self.status = status

    def __enter__(self) -> Opened:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)


def test_a_release_asset_of_this_repository_is_downloaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    asked: list[str] = []

    def urlopen(url: str, **_kwargs: Any) -> Opened:
        asked.append(url)
        return Opened(b"tar bytes")

    monkeypatch.setattr(restore.urllib.request, "urlopen", urlopen)
    url = f"{PREFIX}v1.0.0/fixtures-snapshot-v1.0.0.part1.tar"
    got = restore.fetch_source(url, repository=REPO, dest=tmp_path)
    assert got.read_bytes() == b"tar bytes"
    assert got.name == "fixtures-snapshot-v1.0.0.part1.tar"
    assert asked == [url]


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/owner/loremfile/releases/download/v1.0.0/f.part1.tar",
        "https://github.com/other/loremfile/releases/download/v1.0.0/f.part1.tar",
        "https://github.com/owner/loremfile/releases/downloadx/v1.0.0/f.part1.tar",
        "https://github.com.evil.example/owner/loremfile/releases/download/v1.0.0/f.part1.tar",
        "https://github.com/owner/loremfile/releases/download/v1.0.0/notes.md",
        "https://github.com/owner/loremfile/releases/download/v1.0.0/../../x.tar",
        "https://github.com/owner/loremfile/releases/download/v1.0.0/f.tar?x=1",
        "https://github.com/owner/loremfile/releases/download/f.part1.tar",
        "https://github.com/owner/loremfile/releases/download/../f.part1.tar",
    ],
)
def test_anything_else_from_the_network_is_refused_before_it_is_requested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str
) -> None:
    asked: list[str] = []
    monkeypatch.setattr(restore.urllib.request, "urlopen", lambda u, **_k: asked.append(u))
    with pytest.raises(RestoreError, match="only release archive parts"):
        restore.fetch_source(url, repository=REPO, dest=tmp_path)
    assert asked == []


def test_a_failed_download_is_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def urlopen(url: str, **_kwargs: Any) -> Opened:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(restore.urllib.request, "urlopen", urlopen)
    with pytest.raises(RestoreError, match="HTTP 404"):
        restore.fetch_source(f"{PREFIX}v1.0.0/f.part1.tar", repository=REPO, dest=tmp_path)


def test_a_local_tar_is_read_in_place_and_anything_else_is_refused(tmp_path: Path) -> None:
    part = tar_of(tmp_path / "f.part1.tar", {})
    assert restore.fetch_source(str(part), repository=REPO, dest=tmp_path / "in") == part
    (tmp_path / "notes.md").write_text("x")
    for bad in (tmp_path / "notes.md", tmp_path / "missing.tar"):
        with pytest.raises(RestoreError, match=r"not a local \.tar"):
            restore.fetch_source(str(bad), repository=REPO, dest=tmp_path / "in")


# --- members -------------------------------------------------------------------------------


def test_verified_members_are_taken_and_everything_else_is_reported(tmp_path: Path) -> None:
    part = tar_of(
        tmp_path / "p.tar",
        {**BODIES, "txt/c.txt": b"taken down", "unknown/x.bin": b"?"},
        directories=("pdf/",),
    )
    found = restore.extract_verified([part], entries(), tmp_path / "work")
    assert sorted(found.files) == sorted(BODIES)
    assert found.blockers == []
    assert any("txt/c.txt" in note and "never restored" in note for note in found.notes)
    assert any("unknown/x.bin" in note for note in found.notes)
    for path, stored in found.files.items():
        assert stored.read_bytes() == BODIES[path]
        assert stored.parent == tmp_path / "work", "members land in scratch files, not their names"


def test_a_member_whose_bytes_do_not_match_stops_the_restore(tmp_path: Path) -> None:
    part = tar_of(tmp_path / "p.tar", {"pdf/a.pdf": BODIES["pdf/a.pdf"], "png/b.png": b"tampered"})
    found = restore.extract_verified([part], entries(), tmp_path / "work")
    assert list(found.files) == ["pdf/a.pdf"]
    assert len(found.blockers) == 1
    assert "png/b.png" in found.blockers[0]
    assert "manifest does not describe" in found.blockers[0]


def test_a_member_name_cannot_choose_where_it_is_written(tmp_path: Path) -> None:
    part = tar_of(tmp_path / "p.tar", {"../../escape.pdf": b"x", "pdf/a.pdf": BODIES["pdf/a.pdf"]})
    found = restore.extract_verified([part], entries(), tmp_path / "work")
    assert list(found.files) == ["pdf/a.pdf"], "control: the legitimate member is still taken"
    assert not list(tmp_path.parent.rglob("escape.pdf"))


def test_only_decides_which_members_are_read(tmp_path: Path) -> None:
    part = tar_of(tmp_path / "p.tar", {"pdf/a.pdf": BODIES["pdf/a.pdf"], "png/b.png": b"tampered"})
    found = restore.extract_verified([part], entries(), tmp_path / "work", only={"pdf/a.pdf"})
    assert list(found.files) == ["pdf/a.pdf"]
    assert found.blockers == [], "a member --only excludes is not read, so cannot block"


def test_a_path_in_two_parts_is_taken_once(tmp_path: Path) -> None:
    one = tar_of(tmp_path / "one.tar", {"pdf/a.pdf": BODIES["pdf/a.pdf"]})
    two = tar_of(tmp_path / "two.tar", {"pdf/a.pdf": BODIES["pdf/a.pdf"]})
    found = restore.extract_verified([one, two], entries(), tmp_path / "work")
    assert list(found.files) == ["pdf/a.pdf"]
    assert len(list((tmp_path / "work").iterdir())) == 1


def test_an_unreadable_archive_is_a_blocker(tmp_path: Path) -> None:
    broken = tmp_path / "broken.tar"
    broken.write_bytes(b"not a tar at all" * 100)
    assert restore.extract_verified([broken], entries(), tmp_path / "work").blockers


# --- a directory -------------------------------------------------------------------------


def test_a_directory_is_verified_in_place(tmp_path: Path) -> None:
    root = tmp_path / "extracted"
    (root / "pdf").mkdir(parents=True)
    (root / "png").mkdir()
    (root / "txt").mkdir()
    (root / "pdf/a.pdf").write_bytes(BODIES["pdf/a.pdf"])
    (root / "png/b.png").write_bytes(b"tampered")
    (root / "txt/c.txt").write_bytes(b"taken down")
    found = restore.files_from_dir(root, entries())
    assert list(found.files) == ["pdf/a.pdf"]
    assert any("png/b.png" in blocker for blocker in found.blockers)
    assert any("txt/c.txt" in note for note in found.notes)


def test_a_symlink_out_of_the_directory_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(BODIES["pdf/a.pdf"])
    root = tmp_path / "extracted"
    (root / "pdf").mkdir(parents=True)
    (root / "pdf/a.pdf").symlink_to(outside)
    found = restore.files_from_dir(root, entries())
    assert found.files == {}
    assert any("outside" in blocker for blocker in found.blockers)


# --- the plan -------------------------------------------------------------------------------


def available_of(*paths: str) -> Available:
    return Available(files={path: Path(f"/scratch/{path}") for path in paths})


def by_path() -> dict[str, dict[str, Any]]:
    return {entry["path"]: entry for entry in entries()}


def test_missing_objects_are_uploaded_and_matching_ones_skipped() -> None:
    sha_b = by_path()["png/b.png"]["sha256"]
    plan = restore.plan_restore(available_of(*BODIES), {"png/b.png": sha_b}, by_path())
    actions = {step.key: step.action for step in plan.steps}
    assert actions == {"pdf/a.pdf": Action.UPLOAD, "png/b.png": Action.SKIP}
    assert plan.ok


@pytest.mark.parametrize("stored", ["f" * 64, UNVERIFIABLE])
def test_a_live_object_with_other_bytes_is_replaced_not_skipped(stored: str) -> None:
    plan = restore.plan_restore(available_of("pdf/a.pdf"), {"pdf/a.pdf": stored}, by_path())
    (step,) = plan.steps
    assert step.action is Action.REPLACE
    assert "lock" in step.reason


def test_sources_with_nothing_restorable_are_a_blocker() -> None:
    """ "Restored 0 fixtures" and "restored everything" must not look alike."""
    assert not restore.plan_restore(Available(), {}, by_path()).ok


def test_an_only_path_the_sources_lack_is_a_blocker() -> None:
    plan = restore.plan_restore(
        available_of("pdf/a.pdf"), {}, by_path(), only={"pdf/a.pdf", "png/b.png"}
    )
    assert any("png/b.png" in blocker for blocker in plan.blockers)


# --- the command ----------------------------------------------------------------------------


class Bucket:
    """Enough of S3 for restore: a listing, HEADs, and uploads that a lock may refuse."""

    def __init__(self, objects: dict[str, str], *, locked: set[str] = frozenset()) -> None:
        self.objects = objects
        self.locked = locked
        self.uploads: list[str] = []

    def list_objects_v2(self, **_kwargs: Any) -> dict[str, Any]:
        return {"Contents": [{"Key": key} for key in sorted(self.objects)], "IsTruncated": False}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        return {"Metadata": {"sha256": self.objects[kwargs["Key"]]}}

    def upload_file(self, **kwargs: Any) -> None:
        if kwargs["Key"] in self.locked:
            raise S3UploadFailedError(f"Failed to upload {kwargs['Key']}: AccessDenied")
        self.uploads.append(kwargs["Key"])


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"catalog_version": "1.0.0", "fixtures": entries()}))
    monkeypatch.setattr(config, "manifest_path", lambda: manifest)
    purged: list[list[str]] = []
    monkeypatch.setattr(
        purge, "purge_restored_urls", lambda _c, urls: purged.append(urls) or purge.PurgeReport()
    )
    monkeypatch.setattr(cli, "_zone_client", object)
    monkeypatch.setattr(r2, "bucket_name", lambda: "bucket")
    part = tar_of(tmp_path / "p.part1.tar", BODIES)
    return {"part": part, "purged": purged}


def run(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, bucket: Bucket, *extra: str) -> Any:
    monkeypatch.setattr(r2, "client", lambda: bucket)
    result = CliRunner().invoke(
        cli.main, ["upload", "--restore", str(world["part"]), *extra, "--json"]
    )
    return result, json.loads(result.stdout)


def test_a_dry_run_verifies_and_plans_but_writes_nothing(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    bucket = Bucket({"png/b.png": "f" * 64})
    result, report = run(world, monkeypatch, bucket, "--dry-run")
    assert result.exit_code == 0, result.output
    assert (report["summary"]["upload"], report["summary"]["replace"]) == (1, 1)
    assert bucket.uploads == []
    assert world["purged"] == []


def test_restore_writes_the_missing_replaces_the_wrong_and_purges_both(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    bucket = Bucket({"png/b.png": "f" * 64})
    result, report = run(world, monkeypatch, bucket)
    assert result.exit_code == 0, result.output
    assert sorted(bucket.uploads) == ["pdf/a.pdf", "png/b.png"]
    assert report["summary"]["written"] == 2
    assert sorted(world["purged"][0]) == [f"https://{config.SITE_HOST}/{p}" for p in sorted(BODIES)]


def test_a_refused_replacement_fails_and_says_how_to_lift_the_lock(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    bucket = Bucket({"png/b.png": "f" * 64}, locked={"png/b.png"})
    result, report = run(world, monkeypatch, bucket)
    assert result.exit_code == 1
    assert bucket.uploads == ["pdf/a.pdf"], "the other write still happens"
    (error,) = report["errors"]
    assert "png/b.png" in error
    assert "docs/11 §7.8" in error
    assert world["purged"] == [[f"https://{config.SITE_HOST}/pdf/a.pdf"]]
    statuses = {item["path"]: item["status"] for item in report["items"]}
    assert statuses == {"pdf/a.pdf": "written", "png/b.png": "refused"}


def test_restore_is_its_own_mode() -> None:
    result = CliRunner().invoke(cli.main, ["upload", "--fixtures", "--restore", "x.tar", "--json"])
    assert result.exit_code == 1
    assert "choose exactly one" in json.loads(result.stdout)["errors"][0]


# --- infra.yml -------------------------------------------------------------------------------


def infra() -> dict[Any, Any]:
    return dict(yaml.safe_load(INFRA.read_text(encoding="utf-8")))


def restore_steps() -> list[dict[str, Any]]:
    return list(infra()["jobs"]["restore"]["steps"])


def test_the_restore_and_redact_modes_are_offered() -> None:
    triggers = infra().get("on", infra().get(True))
    options = triggers["workflow_dispatch"]["inputs"]["mode"]["options"]
    assert {"restore-dry-run", "restore", "redact-dry-run", "redact"} <= set(options)


def test_the_inputs_reach_the_shell_only_through_the_environment() -> None:
    text = "\n".join(str(step.get("run", "")) for step in restore_steps())
    # The expression form, not the bare name: the guard's own message names the input.
    assert "inputs.restore_archive_url" not in text
    assert "inputs.restore_only" not in text
    assert "restore_archive_url is empty" in text, "control: these are the scripts that run"
    guard = next(step for step in restore_steps() if step.get("id") == "flags")
    assert guard["env"] == {
        "SOURCES": "${{ inputs.restore_archive_url }}",
        "ONLY": "${{ inputs.restore_only }}",
    }


def test_only_a_real_restore_writes_and_then_verifies_what_it_wrote() -> None:
    by_name = {step.get("name", ""): step for step in restore_steps()}
    dry = by_name["Plan the restore (downloads and verifies; writes nothing)"]
    real = by_name["Restore"]
    verify = by_name["Verify the restored fixtures"]
    assert dry["if"] == "inputs.mode == 'restore-dry-run'"
    assert dry["run"].rstrip().endswith("--dry-run")
    assert real["if"] == "inputs.mode == 'restore'"
    assert "--dry-run" not in real["run"]
    assert "--json > restore.json" in real["run"]
    assert "inputs.mode == 'restore'" in verify["if"]
    assert "verify-live --mode full $paths" in verify["run"], "hash what was written, nothing more"
    names = list(by_name)
    assert names.index("Restore") < names.index("Verify the restored fixtures")


def test_the_verify_step_selects_exactly_the_written_paths(tmp_path: Path) -> None:
    verify = next(s for s in restore_steps() if s.get("name") == "Verify the restored fixtures")
    match = re.search(r"python -c '(.+?)'\)", verify["run"])
    assert match is not None
    items = [
        {"path": "pdf/a.pdf", "status": "written"},
        {"path": "png/b.png", "status": "refused"},
        {"path": "csv/c.csv", "status": "skip"},
    ]
    (tmp_path / "restore.json").write_text(json.dumps({"items": items}))
    done = subprocess.run(  # noqa: S603 - the workflow's own one-liner
        [sys.executable, "-c", match.group(1)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout.strip() == "--only pdf/a.pdf"


def test_the_restore_job_uses_production_inside_the_zone_group() -> None:
    document = infra()
    assert document["jobs"]["restore"]["environment"] == "production"
    assert document["concurrency"]["group"] == "loremfile-zone"


def guard(tmp_path: Path, sources: str, only: str = "") -> tuple[int, str]:
    """Run the workflow's own input check, as the runner would, and return its verdict."""
    script = next(step for step in restore_steps() if step.get("id") == "flags")["run"]
    output = tmp_path / "output"
    output.write_text("")
    sh = shutil.which("sh")
    assert sh is not None
    completed = subprocess.run(  # noqa: S603 - fixed argv; the script is the workflow's own
        [sh, "-c", script],
        env={
            "PATH": os.environ.get("PATH", ""),
            "SOURCES": sources,
            "ONLY": only,
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, output.read_text()


def test_the_workflow_guard_accepts_release_parts_of_this_repository(tmp_path: Path) -> None:
    url = f"{PREFIX}v1.0.0/fixtures-snapshot-v1.0.0.part1.tar"
    code, output = guard(tmp_path, url, only="pdf/a.pdf")
    assert code == 0
    assert output == f"flags= --restore {url} --only pdf/a.pdf\n"


@pytest.mark.parametrize(
    ("sources", "only"),
    [
        ("https://github.com/other/loremfile/releases/download/v1.0.0/f.part1.tar", ""),
        ("https://example.com/f.part1.tar", ""),
        (f"{PREFIX}v1.0.0/notes.md", ""),
        (f"{PREFIX}v1.0.0/sub/f.part1.tar", ""),
        (f"{PREFIX}v1.0.0/f.part1.tar;id", ""),
        ("", ""),
        (f"{PREFIX}v1.0.0/f.part1.tar", "../etc/passwd"),
    ],
)
def test_the_workflow_guard_refuses_everything_else(
    tmp_path: Path, sources: str, only: str
) -> None:
    code, output = guard(tmp_path, sources, only)
    assert code != 0
    assert output == ""
