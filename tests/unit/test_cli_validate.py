"""`loremfile validate` must check what the build produced — no more, no less.

ci.yml runs `build --new` followed by a bare `validate`. On a pull request that adds a
handful of fixtures, `--new` generates only those, so a `validate` that re-derived the
whole catalog would fail on everything the pull request did not touch. Equally, a
`validate` that found nothing and reported success would be a green check proving
nothing. Both were real: the first failed CI, the second is what the guard here prevents.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from loremfile import build as build_module
from loremfile import cli


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
