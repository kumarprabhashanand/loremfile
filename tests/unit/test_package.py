"""M1.1 smoke tests: the package imports and the console script has an entry point.

They also keep `pytest` from exiting 5 ("no tests collected"), which would fail the
`lint-and-test` job added in M1.5.
"""

from __future__ import annotations

import loremfile
from loremfile import cli


def test_version_is_exposed() -> None:
    assert loremfile.__version__


def test_version_flag_exits_zero(capsys) -> None:
    assert cli.main(["--version"]) == 0
    assert loremfile.__version__ in capsys.readouterr().out


def test_no_command_exits_non_zero() -> None:
    assert cli.main([]) != 0
