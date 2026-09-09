"""`manifest adopt` takes CI's bytes without letting anything published change.

M3.6 found that four media fixtures hash differently on GitHub's runners than on the
author's machine: libx264, libvpx and libopus each dispatch on the CPU features they
find, and no ffmpeg flag reaches that choice (`-cpuflags 0` changes nothing). CI is the
authority because CI builds the bytes the deploy uploads, so its entries have to be
committable — and AGENTS.md forbids hand-editing manifest.json.

The refusal in `test_adopting_over_a_published_fixture_is_refused` is the reason this
command can exist at all. Without it, "take CI's answer" would be a way to rewrite the
bytes of something already published, which REQ-2 forbids forever.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from loremfile import build as build_module
from loremfile import cli, config
from loremfile.catalog import Catalog
from loremfile.manifest import Manifest


def run(args: list[str]) -> tuple[int, dict]:
    result = CliRunner().invoke(cli.main, [*args, "--json"])
    payload = json.loads(result.output) if result.output.strip().startswith("{") else {}
    return result.exit_code, payload


@pytest.fixture
def entry() -> dict:
    """A real committed entry, altered as a different machine's build would alter it."""
    committed = Manifest.load()
    original = dict(committed.by_path["pdf/a4-3pages.pdf"])
    original["sha256"] = "0" * 64
    original["bytes"] = original["bytes"] + 17
    return original


def write(tmp_path: Path, entries: list[dict]) -> Path:
    target = tmp_path / "ci-entries.json"
    target.write_text(json.dumps(entries), encoding="utf-8")
    return target


def test_adopting_over_a_published_fixture_is_refused(
    tmp_path: Path, entry: dict, monkeypatch
) -> None:
    """The whole point: published bytes are frozen, whatever any machine now produces."""
    published = Manifest.load()
    monkeypatch.setattr(build_module, "merge_base_manifest", lambda *_a, **_k: published)

    code, payload = run(["manifest", "adopt", "--from", str(write(tmp_path, [entry]))])
    assert code != 0
    assert any("frozen forever" in e for e in payload["errors"])
    assert Manifest.load().by_path["pdf/a4-3pages.pdf"]["sha256"] != "0" * 64, (
        "the manifest was written despite the refusal"
    )


def test_adopting_a_fixture_this_branch_adds_is_allowed(
    tmp_path: Path, entry: dict, monkeypatch
) -> None:
    """The case it exists for: the path is new on this branch, so nothing is frozen yet.

    Writes are redirected into tmp_path so the repository's own manifest is untouched.
    """
    empty = Manifest.load()
    empty.entries = []
    monkeypatch.setattr(build_module, "merge_base_manifest", lambda *_a, **_k: empty)
    for name, filename in (
        ("manifest_path", "manifest.json"),
        ("sha256sums_path", "sha256sums.txt"),
        ("formats_json_path", "formats.json"),
    ):
        monkeypatch.setattr(config, name, lambda f=filename: tmp_path / f)

    code, payload = run(["manifest", "adopt", "--from", str(write(tmp_path, [entry]))])
    assert code == 0, payload
    assert payload["summary"]["adopted"] == 1

    written = json.loads((tmp_path / "manifest.json").read_text())
    by_path = {e["path"]: e for e in written["fixtures"]}
    assert by_path["pdf/a4-3pages.pdf"]["sha256"] == "0" * 64
    assert (tmp_path / "sha256sums.txt").is_file(), "sha256sums.txt must be rewritten too"
    assert (tmp_path / "formats.json").is_file(), "formats.json must be rewritten too"


def test_a_path_that_is_not_in_the_catalog_is_refused(tmp_path: Path, entry: dict) -> None:
    entry["path"] = "mp4/not-a-fixture.mp4"
    code, payload = run(["manifest", "adopt", "--from", str(write(tmp_path, [entry]))])
    assert code != 0
    assert any("not in the catalog" in e for e in payload["errors"])


def test_an_incomplete_entry_is_refused(tmp_path: Path, entry: dict) -> None:
    """A truncated paste must not become a manifest entry with fields missing."""
    del entry["props"]
    del entry["sha256"]
    code, payload = run(["manifest", "adopt", "--from", str(write(tmp_path, [entry]))])
    assert code != 0
    assert any("missing" in e for e in payload["errors"])


def test_the_catalog_and_manifest_still_agree_after_adopting() -> None:
    """Adopting changes bytes, never the fixture list.

    The manifest holds every active fixture *except* those withheld until a run can
    publish them (docs/03 §7.1) — five of them at M3.6.
    """
    loaded = Catalog.load()
    expected = {f.path for f in loaded.fixtures() if not f.awaiting_publication}
    assert {e["path"] for e in Manifest.load().active} == expected
