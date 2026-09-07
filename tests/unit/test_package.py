"""Smoke tests: the package imports and the console script works."""

from __future__ import annotations

from click.testing import CliRunner

import loremfile
from loremfile import cli


def test_version_is_exposed() -> None:
    assert loremfile.__version__


def test_version_flag_exits_zero() -> None:
    result = CliRunner().invoke(cli.main, ["--version"])
    assert result.exit_code == 0
    assert loremfile.__version__ in result.output


def test_no_command_shows_help_and_exits_non_zero() -> None:
    result = CliRunner().invoke(cli.main, [])
    assert result.exit_code != 0
    assert "catalog" in result.output
    assert "manifest" in result.output


def test_unknown_command_exits_non_zero() -> None:
    assert CliRunner().invoke(cli.main, ["nope"]).exit_code != 0
