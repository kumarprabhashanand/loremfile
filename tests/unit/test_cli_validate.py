"""`loremfile validate` must check what the build produced — no more, no less.

ci.yml runs `build --new` followed by a bare `validate`. On a pull request that adds a
handful of fixtures, `--new` generates only those, so a `validate` that re-derived the
whole catalog would fail on everything the pull request did not touch. Equally, a
`validate` that found nothing and reported success would be a green check proving
nothing. Both were real: the first failed CI, the second is what the guard here prevents.

The third case was also real, and cost a red check on the M0 infrastructure pull request:
a build that *correctly* selects nothing, because the branch touches no catalog entry.
That is indistinguishable from "no build ran" if all you have is an empty directory, so
`build` leaves `build/selection.json` behind and `validate` reads it (docs/06 §5).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from loremfile import build as build_module
from loremfile import cli
from loremfile.catalog import Catalog


def run(args: list[str]) -> tuple[int, dict]:
    result = CliRunner().invoke(cli.main, [*args, "--json"])
    payload = json.loads(result.output) if result.output.strip().startswith("{") else {}
    return result.exit_code, payload


def test_empty_build_directory_fails_rather_than_passing_vacuously(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(build_module, "fixtures_dir", lambda: tmp_path / "empty")
    code, payload = run(["validate"])
    assert code != 0
    assert any("build/fixtures is empty" in e for e in payload["errors"])


def test_only_a_path_that_was_not_built_is_an_error(tmp_path: Path, monkeypatch) -> None:
    """An explicit request must be honoured or refused, never quietly skipped."""
    monkeypatch.setattr(build_module, "fixtures_dir", lambda: tmp_path / "empty")
    code, payload = run(["validate", "--only", "txt/lf.txt"])
    assert code != 0
    assert any("not generated" in e for e in payload["errors"])


def test_validates_only_what_is_present(tmp_path: Path, monkeypatch) -> None:
    """The `build --new` then `validate` sequence ci.yml uses."""
    directory = tmp_path / "fixtures"
    (directory / "toml").mkdir(parents=True)
    built = build_module.fixtures_dir() / "toml" / "config.toml"
    if not built.is_file():
        pytest.skip("run `loremfile build --format toml` first")
    (directory / "toml" / "config.toml").write_bytes(built.read_bytes())
    monkeypatch.setattr(build_module, "fixtures_dir", lambda: directory)

    code, payload = run(["validate"])
    assert code == 0, payload
    assert payload["summary"]["validated"] == 1
    assert payload["summary"]["failed"] == 0
    assert payload["summary"]["skipped_not_built"] > 0


def write_receipt(fixtures_directory: Path, selected: list[str]) -> None:
    """The receipt `build` would have left, without paying for a real build."""
    fixtures_directory.mkdir(parents=True, exist_ok=True)
    build_module.receipt_path(fixtures_directory).write_text(
        json.dumps({"selection": "new", "filters": {}, "selected": selected})
    )


def test_a_build_that_selected_nothing_is_not_a_failure(tmp_path: Path, monkeypatch) -> None:
    """An infrastructure-only pull request builds nothing, and that is a pass.

    Negative control: the same empty directory without the receipt is the test above,
    which must still fail. One directory, two verdicts, decided by the receipt.
    """
    directory = tmp_path / "fixtures"
    write_receipt(directory, [])
    monkeypatch.setattr(build_module, "fixtures_dir", lambda: directory)

    code, payload = run(["validate"])
    assert code == 0, payload
    assert payload["summary"]["validated"] == 0
    assert payload["summary"]["selected_by_last_build"] == 0
    assert payload["errors"] == []


def test_a_selected_fixture_never_written_is_an_error(tmp_path: Path, monkeypatch) -> None:
    """A build that reported success but skipped a file must not validate green."""
    directory = tmp_path / "fixtures"
    path = next(iter(Catalog.load().by_path))
    write_receipt(directory, [path])
    monkeypatch.setattr(build_module, "fixtures_dir", lambda: directory)

    code, payload = run(["validate"])
    assert code != 0
    assert any("never written" in e for e in payload["errors"])


def test_a_corrupt_receipt_is_refused_rather_than_ignored(tmp_path: Path, monkeypatch) -> None:
    """Falling back to "no receipt" would silently restore the old ambiguity."""
    directory = tmp_path / "fixtures"
    directory.mkdir(parents=True)
    build_module.receipt_path(directory).write_text("{not json")
    monkeypatch.setattr(build_module, "fixtures_dir", lambda: directory)

    code, payload = run(["validate"])
    assert code != 0
    assert any("unreadable build receipt" in e for e in payload["errors"])


def test_build_leaves_a_receipt_that_validate_then_honours(tmp_path: Path, monkeypatch) -> None:
    """The whole contract, end to end, on one cheap fixture.

    Asserts the wiring rather than the plumbing: `build` writing a receipt is what makes
    the cases above reachable, and nothing else in the suite would notice it going away.
    """
    directory = tmp_path / "fixtures"
    monkeypatch.setattr(build_module, "fixtures_dir", lambda: directory)

    code, payload = run(["build", "--only", "txt/lf.txt"])
    assert code == 0, payload
    assert (directory / "txt" / "lf.txt").is_file()

    receipt = build_module.read_receipt()
    assert receipt is not None
    assert receipt.selected == ("txt/lf.txt",)
    assert receipt.filters["only"] == ["txt/lf.txt"]
    assert build_module.receipt_path(directory).parent == directory.parent, (
        "the receipt must live beside build/fixtures, never inside it — everything "
        "inside is uploaded to the bucket"
    )

    code, payload = run(["validate"])
    assert code == 0, payload
    assert payload["summary"]["validated"] == 1

    build_module.clean(directory)
    assert build_module.read_receipt() is None, "clean must not leave a receipt behind"
