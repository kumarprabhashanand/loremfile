"""`loremfile site build`: the legal values reach the pages and never the output (docs/13 §3b)."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from loremfile import cli

#: Joined at run time, so no file in the repository contains them and `git grep` stays empty.
VALUES = {
    "IMPRINT_NAME": "-".join(["cli", "test", "operator"]),
    "IMPRINT_STREET": "-".join(["cli", "test", "street", "9"]),
    "IMPRINT_POSTAL_CITY": "-".join(["00000", "cli", "test", "city"]),
}


def report(output: str) -> dict[str, object]:
    document: dict[str, object] = json.loads(output[output.index("{\n") :])
    return document


def test_a_production_build_fills_the_pages_and_prints_no_value(tmp_path: Path) -> None:
    out = tmp_path / "site"
    result = CliRunner().invoke(
        cli.main,
        ["site", "build", "--out", str(out), "--legal-values-from-env", "--json"],
        env=VALUES,
    )
    assert result.exit_code == 0, result.output
    assert report(result.output)["summary"] == {
        "keys": report(result.output)["summary"]["keys"],  # type: ignore[index]
        "pages": report(result.output)["summary"]["pages"],  # type: ignore[index]
        "bytes": report(result.output)["summary"]["bytes"],  # type: ignore[index]
        "legal": "filled",
    }
    assert all(value not in result.output for value in VALUES.values())
    imprint = (out / "legal" / "imprint.html").read_text()
    assert all(value in imprint for value in VALUES.values())


def test_a_production_build_without_the_values_fails_and_names_them(tmp_path: Path) -> None:
    empty = dict.fromkeys(VALUES, "")
    result = CliRunner().invoke(
        cli.main,
        ["site", "build", "--out", str(tmp_path / "site"), "--legal-values-from-env", "--json"],
        env=empty,
    )
    assert result.exit_code == 1
    assert "IMPRINT_NAME" in result.output


def test_a_pull_request_build_keeps_the_placeholders(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli.main, ["site", "build", "--out", str(tmp_path / "site"), "--json"]
    )
    assert result.exit_code == 0, result.output
    assert report(result.output)["summary"]["legal"] == "placeholders"  # type: ignore[index]
