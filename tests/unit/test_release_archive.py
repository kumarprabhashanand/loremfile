"""release.yml's archive: the right tag, the right members, the published bytes (docs/09 §3.5).

The archive is the restore path when the bucket is gone (docs/11 §7.6), so every way of
getting it wrong without an error is pinned here: a tag that does not name the manifest's
version; a previous release chosen wrongly, which makes a delta silently omit fixtures; a
member fetched from anywhere but production; and release notes that never existed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from loremfile import cli, config
from loremfile.infra import release, verify_live
from loremfile.infra.release import Plan, ReleaseError
from loremfile.manifest import Manifest, render_sha256sums

ROOT = Path(__file__).resolve().parents[2]

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"


def entry(path: str, body: bytes, **extra: Any) -> dict[str, Any]:
    return {
        "path": path,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "status": "active",
        **extra,
    }


def document(version: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"catalog_version": version, "fixtures": entries}


BODIES = {"pdf/a.pdf": b"%PDF-a", "png/b.png": b"\x89PNG-b", "csv/c.csv": b"x,y\n1,2\n"}
CHANGELOG = """# Changelog

## [Unreleased]

## [1.1.0] - 2026-10-01

### Added

- `csv/c.csv`

## [1.0.0] - 2026-09-20

### Added

- `pdf/a.pdf`, `png/b.png`
"""


# --- tags and plans ------------------------------------------------------------------


@pytest.mark.parametrize("tag", ["1.0.0", "v1.0", "v1.0.0-rc1", "release-1", "v01.a.0"])
def test_only_vmajor_minor_patch_is_a_release_tag(tag: str) -> None:
    with pytest.raises(ReleaseError, match="not a release tag"):
        release.version_of(tag)


def test_a_release_tag_parses_to_its_numbers() -> None:
    """Control for the test above: the pattern does accept a real tag."""
    assert release.version_of("v1.10.2") == (1, 10, 2)


def test_the_tag_must_name_the_manifest_version() -> None:
    release.check_tag("v1.2.0", "1.2.0")
    with pytest.raises(ReleaseError, match=r"v1\.2\.0 does not match .* 1\.3\.0"):
        release.check_tag("v1.2.0", "1.3.0")


@pytest.mark.parametrize(
    ("tag", "previous", "since"),
    [
        ("v1.0.0", None, None),  # the first release
        ("v1.1.0", "v1.0.0", "v1.0.0"),
        ("v1.1.1", "v1.1.0", "v1.1.0"),  # a patch release is a delta, usually empty
        ("v1.10.0", "v1.9.4", None),  # every 10th minor
        ("v1.20.0", "v1.19.0", None),
        ("v1.10.1", "v1.10.0", "v1.10.0"),  # not a patch of the 10th minor
        ("v2.0.0", "v1.12.0", "v1.12.0"),  # minor 0 is not a 10th minor
    ],
)
def test_a_snapshot_for_the_first_release_and_every_tenth_minor(
    tag: str, previous: str | None, since: str | None
) -> None:
    plan = release.plan_release(tag, previous)
    assert plan.since == since
    assert plan.mode == ("snapshot" if since is None else "delta")


def test_asset_names_say_what_the_archive_covers() -> None:
    assert Plan(tag="v1.0.0", since=None).stem == "fixtures-snapshot-v1.0.0"
    assert Plan(tag="v1.1.0", since="v1.0.0").stem == "fixtures-v1.0.0-v1.1.0"


# --- the previous release, from a real repository -------------------------------------


def git(repo: Path, *args: str) -> str:
    executable = shutil.which("git")
    assert executable is not None
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            executable,
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
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
        text=True,
    ).stdout.strip()


def commit(repo: Path, manifest: dict[str, Any], message: str, *, tag: str | None = None) -> None:
    (repo / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    if tag:
        git(repo, "tag", tag)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """v1.0.0 (a, b) → v1.1.0 (+ c) → HEAD at v1.2.0 (unchanged). Also: a pre-release tag,
    a non-release tag, and a higher tag on a branch that HEAD does not contain."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    a, b, c = (entry(path, body) for path, body in BODIES.items())
    commit(root, document("1.0.0", [a, b]), "one", tag="v1.0.0")
    git(root, "tag", "docs-snapshot")
    commit(root, document("1.1.0", [a, b, c]), "two", tag="v1.1.0")
    git(root, "tag", "v1.1.1-rc1")
    commit(root, document("1.2.0", [a, b, c]), "three", tag="v1.2.0")
    git(root, "checkout", "-q", "-b", "side")
    commit(root, document("9.0.0", [a]), "elsewhere", tag="v9.0.0")
    git(root, "checkout", "-q", "v1.2.0")
    return root


def test_the_previous_release_is_the_highest_earlier_tag_reachable(repo: Path) -> None:
    assert release.previous_tag("HEAD", "v1.2.0", cwd=repo) == "v1.1.0"


def test_earlier_releases_step_down_and_the_first_has_none(repo: Path) -> None:
    """Negative control: the lookup is not a constant, and it can return None."""
    assert release.previous_tag("HEAD", "v1.1.0", cwd=repo) == "v1.0.0"
    assert release.previous_tag("HEAD", "v1.0.0", cwd=repo) is None


def test_versions_compare_as_numbers_not_strings(tmp_path: Path) -> None:
    """As strings "v1.9.0" > "v1.10.0" — a delta against v1.9.0 would reship v1.10.0."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    commit(root, document("1.9.0", []), "nine", tag="v1.9.0")
    commit(root, document("1.10.0", []), "ten", tag="v1.10.0")
    commit(root, document("1.11.0", []), "eleven", tag="v1.11.0")
    assert release.previous_tag("HEAD", "v1.11.0", cwd=root) == "v1.10.0"


def test_no_tags_at_all_is_the_first_release_not_an_error(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    commit(root, document("1.0.0", []), "only")
    assert release.previous_tag("HEAD", "v1.0.0", cwd=root) is None


def test_outside_a_repository_the_lookup_fails_rather_than_answering(tmp_path: Path) -> None:
    """ "No previous tag" means a snapshot. A git failure must not be mistaken for it."""
    with pytest.raises(ReleaseError, match="git tag --merged"):
        release.previous_tag("HEAD", "v1.0.0", cwd=tmp_path)


def test_an_earlier_manifest_is_read_from_git(repo: Path) -> None:
    earlier = release.manifest_at("v1.0.0", cwd=repo)
    assert earlier.catalog_version == "1.0.0"
    assert sorted(e["path"] for e in earlier.entries) == ["pdf/a.pdf", "png/b.png"]
    with pytest.raises(ReleaseError, match=r"cannot read manifest\.json at v0\.9\.0"):
        release.manifest_at("v0.9.0", cwd=repo)


# --- members ---------------------------------------------------------------------------


def test_a_delta_holds_only_what_the_previous_release_lacked(repo: Path) -> None:
    current = release.manifest_at("v1.1.0", cwd=repo)
    delta = release.members(Plan(tag="v1.1.0", since="v1.0.0"), current, cwd=repo)
    assert [e["path"] for e in delta] == ["csv/c.csv"]
    # Control: a snapshot of the same manifest holds everything.
    snapshot = release.members(Plan(tag="v1.1.0", since=None), current, cwd=repo)
    assert [e["path"] for e in snapshot] == ["csv/c.csv", "pdf/a.pdf", "png/b.png"]


def test_a_tombstone_is_never_a_member(repo: Path) -> None:
    a, b, c = (entry(path, body) for path, body in BODIES.items())
    removed = {**c, "status": "removed", "reason": "takedown", "removed_at": "2026-10-02"}
    current = Manifest.from_document(document("1.1.0", [a, b, removed]))
    snapshot = release.members(Plan(tag="v1.1.0", since=None), current, cwd=repo)
    assert "csv/c.csv" not in [e["path"] for e in snapshot]


# --- the published bytes -----------------------------------------------------------------


def test_members_are_fetched_from_production_with_get(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[str, str]] = []

    def fetch(path: str, *, method: str = "HEAD", **_kwargs: Any) -> verify_live.Response:
        asked.append((path, method))
        return verify_live.Response(status=200, headers={}, body=b"%PDF-a")

    monkeypatch.setattr(verify_live, "fetch", fetch)
    assert release.fetch_published("pdf/a.pdf") == b"%PDF-a"
    assert asked == [("/pdf/a.pdf", "GET")]


@pytest.mark.parametrize(("status", "said"), [(404, "404"), (403, "403"), (0, "no response")])
def test_anything_but_200_is_an_error_naming_the_answer(
    monkeypatch: pytest.MonkeyPatch, status: int, said: str
) -> None:
    monkeypatch.setattr(
        verify_live,
        "fetch",
        lambda _path, **_k: verify_live.Response(status=status, headers={}, body=b""),
    )
    with pytest.raises(ReleaseError, match=f"production answered {said}"):
        release.fetch_published("pdf/a.pdf")


# --- notes ------------------------------------------------------------------------------


def test_the_notes_are_exactly_the_versions_section() -> None:
    notes = release.changelog_excerpt(CHANGELOG, "1.1.0")
    assert notes.startswith("## [1.1.0] - 2026-10-01")
    assert "`csv/c.csv`" in notes
    assert "1.0.0" not in notes, "the next section must not bleed in"


def test_missing_or_empty_notes_are_errors() -> None:
    with pytest.raises(ReleaseError, match=r"no `## \[1\.2\.0\]` section"):
        release.changelog_excerpt(CHANGELOG, "1.2.0")
    with pytest.raises(ReleaseError, match="is empty"):
        release.changelog_excerpt("## [1.2.0]\n\n## [1.1.0]\n\n- x\n", "1.2.0")


def test_a_version_is_matched_literally() -> None:
    """Unescaped, "1.1.0" is a pattern that also matches "1x1x0"."""
    with pytest.raises(ReleaseError):
        release.changelog_excerpt("## [1x1x0]\n\n- x\n", "1.1.0")


# --- assembly --------------------------------------------------------------------------


class Served:
    """Production, as far as the archive can tell: a map of paths to bytes."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def __call__(self, path: str) -> bytes:
        self.asked.append(path)
        return BODIES[path]


def current_manifest(tmp_path: Path, version: str = "1.1.0") -> tuple[Manifest, Path]:
    data = document(version, [entry(path, body) for path, body in BODIES.items()])
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return Manifest.from_document(data), path


def test_a_release_writes_every_asset_from_the_served_bytes(tmp_path: Path) -> None:
    current, manifest_file = current_manifest(tmp_path)
    out = tmp_path / "out"
    served = Served()
    plan = Plan(tag="v1.1.0", since=None)
    entries = sorted(current.active, key=lambda e: e["path"])
    assets = release.assemble(
        plan,
        current,
        entries,
        manifest_file=manifest_file,
        changelog=CHANGELOG,
        out_dir=out,
        fetch=served,
    )
    assert {path.name for path in assets.files} == {
        "fixtures-snapshot-v1.1.0.part1.tar",
        "parts.txt",
        "manifest.json",
        "sha256sums.txt",
        "notes.md",
    }
    assert sorted(served.asked) == sorted(BODIES)
    assert (out / "manifest.json").read_bytes() == manifest_file.read_bytes()
    assert (out / "sha256sums.txt").read_text() == render_sha256sums(current)
    with tarfile.open(out / "fixtures-snapshot-v1.1.0.part1.tar") as tar:
        assert sorted(tar.getnames()) == sorted(BODIES)


def test_a_tag_run_without_notes_fails_before_downloading_anything(tmp_path: Path) -> None:
    current, manifest_file = current_manifest(tmp_path, version="1.2.0")
    served = Served()
    with pytest.raises(ReleaseError, match=r"no `## \[1\.2\.0\]` section"):
        release.assemble(
            Plan(tag="v1.2.0", since=None),
            current,
            list(current.active),
            manifest_file=manifest_file,
            changelog=CHANGELOG,
            out_dir=tmp_path / "out",
            fetch=served,
        )
    assert served.asked == [], "a release that cannot be published must not download first"


def test_a_rehearsal_without_notes_still_assembles_and_says_so(tmp_path: Path) -> None:
    current, manifest_file = current_manifest(tmp_path, version="1.2.0")
    served = Served()
    assets = release.assemble(
        Plan(tag="v1.2.0", since=None),
        current,
        list(current.active),
        manifest_file=manifest_file,
        changelog=CHANGELOG,
        out_dir=tmp_path / "out",
        fetch=served,
        rehearsal=True,
    )
    assert assets.notes is None
    assert assets.archive.members == len(BODIES)
    assert "notes.md" not in {path.name for path in assets.files}


def test_an_output_directory_that_is_not_empty_is_refused(tmp_path: Path) -> None:
    """release.yml attaches every file in it; a leftover would be published."""
    current, manifest_file = current_manifest(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "leftover.tar").write_bytes(b"old")
    with pytest.raises(ReleaseError, match="not empty"):
        release.assemble(
            Plan(tag="v1.1.0", since=None),
            current,
            list(current.active),
            manifest_file=manifest_file,
            changelog=CHANGELOG,
            out_dir=out,
            fetch=Served(),
        )


def test_the_tag_is_checked_again_at_assembly(tmp_path: Path) -> None:
    current, manifest_file = current_manifest(tmp_path)
    with pytest.raises(ReleaseError, match="does not match"):
        release.assemble(
            Plan(tag="v9.9.9", since=None),
            current,
            list(current.active),
            manifest_file=manifest_file,
            changelog=CHANGELOG,
            out_dir=tmp_path / "out",
            fetch=Served(),
        )


# --- the command, end to end against a scratch repository -------------------------------


def test_the_command_plans_fetches_and_writes(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HEAD is v1.2.0 and adds nothing to v1.1.0: an empty delta, with the notes."""
    (repo / "CHANGELOG.md").write_text(
        CHANGELOG.replace("## [1.1.0]", "## [1.2.0]\n\n- nothing new\n\n## [1.1.0]")
    )
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "manifest_path", lambda: repo / "manifest.json")
    monkeypatch.setattr(
        verify_live,
        "fetch",
        lambda path, **_k: verify_live.Response(200, {}, BODIES[path.lstrip("/")]),
    )
    out = tmp_path / "assets"
    result = CliRunner().invoke(
        cli.main, ["release", "archive", "--tag", "v1.2.0", "--out", str(out), "--json"]
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)["summary"]
    assert (summary["mode"], summary["since"], summary["members"]) == ("delta", "v1.1.0", 0)
    assert (out / "notes.md").is_file()

    # Control: the same command with --snapshot archives every fixture.
    result = CliRunner().invoke(
        cli.main,
        [
            "release",
            "archive",
            "--tag",
            "v1.2.0",
            "--snapshot",
            "--out",
            str(tmp_path / "s"),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["summary"]["members"] == len(BODIES)


def test_since_and_snapshot_are_exclusive() -> None:
    result = CliRunner().invoke(cli.main, ["release", "archive", "--since", "v1.0.0", "--snapshot"])
    assert result.exit_code == 2
    assert "exclusive" in result.output


# --- release.yml -----------------------------------------------------------------------


def workflow() -> dict[Any, Any]:
    return dict(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))


def steps(job: str) -> list[dict[str, Any]]:
    return list(workflow()["jobs"][job]["steps"])


def test_it_runs_on_version_tags_and_by_dispatch_only() -> None:
    triggers = workflow().get("on", workflow().get(True))  # PyYAML reads `on:` as True
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"tags": ["v*"]}


def test_only_the_tag_job_can_write_and_it_needs_a_pushed_tag() -> None:
    document_ = workflow()
    assert document_["permissions"] == {"contents": "read"}
    jobs = document_["jobs"]
    assert jobs["release"]["permissions"] == {"contents": "write"}
    assert "github.event_name == 'push'" in jobs["release"]["if"]
    assert "github.ref_type == 'tag'" in jobs["release"]["if"]
    assert "permissions" not in jobs["rehearse"]
    assert jobs["rehearse"]["if"] == "github.event_name == 'workflow_dispatch'"


def test_no_job_uses_an_environment_or_a_secret() -> None:
    """`production` admits only main; a tag-started job could not read it, and needs none."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.token" in text, "empty-set control: this is the release workflow"
    assert "secrets." not in text
    for name, job in workflow()["jobs"].items():
        assert "environment" not in job, name


def test_the_release_job_fetches_tags_archives_then_publishes_the_pushed_tag() -> None:
    release_steps = steps("release")
    assert release_steps[0]["with"]["fetch-depth"] == 0
    runs = [step.get("run", "") for step in release_steps]
    archive = next(i for i, run in enumerate(runs) if "loremfile release archive" in run)
    publish = next(i for i, run in enumerate(runs) if "gh release create" in run)
    assert archive < publish
    assert '--tag "$GITHUB_REF_NAME"' in runs[archive]
    assert "--rehearsal" not in runs[archive]
    assert "--verify-tag" in runs[publish]
    assert '--repo "$GITHUB_REPOSITORY"' in runs[publish]


def test_the_rehearsal_never_publishes() -> None:
    runs = [step.get("run", "") for step in steps("rehearse")]
    assert any("loremfile release archive --rehearsal" in run for run in runs)
    assert not any("gh release" in run for run in runs)


# --- a release that already exists for the tag -----------------------------------------------
# A history rewrite re-points a tag, and the push fires release.yml again. The published
# release must be left alone, and the run must go green only if it holds exactly what the run
# assembled (after the history rewrite the run went red instead, on "a release with the same
# tag name already exists", with the release untouched).


def _assembled(tmp_path: Path) -> Path:
    out = tmp_path / "release-assets"
    out.mkdir()
    (out / "manifest.json").write_bytes(b'{"fixtures": []}\n')
    (out / "notes.md").write_bytes(b"Release one.\n")
    return out


def _as_published(directory: Path) -> list[dict[str, object]]:
    return [
        {"name": p.name, "size": p.stat().st_size, "digest": f"sha256:{release.sha256_file(p)}"}
        for p in sorted(directory.iterdir())
    ]


def test_an_identical_existing_release_has_no_differences(tmp_path: Path) -> None:
    assets = _assembled(tmp_path)
    assert release.existing_release_differences(assets, _as_published(assets)) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda pub: pub[:1], "notes.md: assembled here, not on the release"),
        (
            lambda pub: [*pub, {"name": "extra.tar", "size": 1, "digest": "sha256:0"}],
            "extra.tar: on the release",
        ),
        (lambda pub: [{**pub[0], "size": 1}, pub[1]], "manifest.json: 1 bytes on the release"),
        (
            lambda pub: [{**pub[0], "digest": "sha256:" + "0" * 64}, pub[1]],
            "manifest.json: sha256 differs",
        ),
        (
            lambda pub: [{k: v for k, v in pub[0].items() if k != "digest"}, pub[1]],
            "no sha256 digest",
        ),
    ],
)
def test_every_kind_of_difference_is_reported(tmp_path: Path, change, expected: str) -> None:
    """Negative controls: each way an existing release can differ must be caught. A match that
    cannot be verified — no digest — is a difference, not a pass."""
    assets = _assembled(tmp_path)
    found = release.existing_release_differences(assets, change(_as_published(assets)))
    assert any(expected in line for line in found), found


def _fake_gh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: str = "",
    stderr: str = "",
    code: int = 0,
) -> None:
    """A real executable named gh on PATH, so the subprocess call itself runs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "gh"
    script.write_text(
        f"#!/bin/sh\nprintf '%s' '{stdout}'\nprintf '%s' '{stderr}' >&2\nexit {code}\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")


def test_no_release_for_the_tag_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_gh(tmp_path, monkeypatch, stderr="gh: Not Found (HTTP 404)", code=1)
    assert release.published_release("o/r", "v1.1.0") is None


def test_a_release_that_cannot_be_read_is_an_error_not_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read as "no release", a failed lookup would create a second one."""
    _fake_gh(tmp_path, monkeypatch, stderr="gh: Server Error (HTTP 502)", code=1)
    with pytest.raises(release.ReleaseError, match="502"):
        release.published_release("o/r", "v1.1.0")


def test_an_existing_release_returns_its_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_gh(tmp_path, monkeypatch, stdout='{"assets": [{"name": "notes.md", "size": 13}]}')
    assert release.published_release("o/r", "v1.1.0") == [{"name": "notes.md", "size": 13}]


@pytest.mark.parametrize(
    ("published", "code"),
    [(None, 3), ("same", 0), ("different", 1)],
)
def test_check_existing_exits_0_on_a_match_3_on_no_release_and_1_otherwise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, published: str | None, code: int
) -> None:
    """The workflow creates a release only on 3. 2 is avoided because click uses it."""
    assets = _assembled(tmp_path)
    answer = {None: None, "same": _as_published(assets), "different": _as_published(assets)[:1]}[
        published
    ]
    monkeypatch.setattr(release, "published_release", lambda _repo, _tag: answer)
    result = CliRunner().invoke(
        cli.main,
        ["release", "check-existing", "--tag", "v1.1.0", "--repo", "o/r", "--dir", str(assets)],
    )
    assert result.exit_code == code, result.output


def test_the_workflow_creates_a_release_only_when_none_exists() -> None:
    step = next(
        s
        for s in yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())[
            "jobs"
        ]["release"]["steps"]
        if s.get("name") == "Publish the release"
    )
    run = step["run"]
    assert run.index("release check-existing") < run.index("gh release create")
    assert "3) gh release create" in run, "create only when check-existing reports no release"
    assert "*) exit 1" in run, "a differing or unreadable release must fail the run"
