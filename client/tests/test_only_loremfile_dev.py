"""The client talks to loremfile.dev and to nothing else.

Four ways of asking, because one of them alone would be easy to satisfy and still be
wrong: the constant is the production host; the override refuses anything that is not
loopback; no flag or environment variable reaches the base URL; and no other host appears
in the source at all. The override exists only so the rest of this suite can run without
touching production — the same seam, and the same loopback-only rule, as the repository's
GitHub Action.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from loremfile_client import api, cli

PACKAGE = Path(api.__file__).parent


def test_the_constant_is_production() -> None:
    assert api.BASE_URL == "https://loremfile.dev/"


def test_with_no_override_it_is_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(api.OVERRIDE, raising=False)
    assert api.base_url() == "https://loremfile.dev/"


@pytest.mark.parametrize(
    "value",
    [
        "https://loremfile.dev.evil.test/",  # the host name as a prefix
        "https://evil.test/loremfile.dev/",  # and as a path
        "http://127.0.0.1.evil.test:8080/",  # and the loopback address as a prefix
        "https://example.com/",
        "file:///etc/passwd",
        "http://169.254.169.254/",  # the cloud metadata address
        " https://evil.test/",  # leading space
    ],
)
def test_the_override_refuses_anything_but_loopback(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(api.OVERRIDE, value)
    with pytest.raises(api.Refused, match="loopback address only"):
        api.base_url()


@pytest.mark.parametrize(
    "value", ["http://127.0.0.1:8080", "http://localhost:9/", "http://[::1]:1234"]
)
def test_the_override_accepts_loopback(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """The control: the refusals above are refusals, not a function that rejects everything."""
    monkeypatch.setenv(api.OVERRIDE, value)
    assert api.base_url().startswith(value.rstrip("/"))


def test_no_command_line_flag_reaches_the_host() -> None:
    """A mirror flag would contradict the README, so there must not be one — checked on
    the parser rather than by reading the source, so a flag added later is caught."""
    parser = cli.build_parser()
    options = {
        option
        for action in parser._subparsers._group_actions[0].choices.values()
        for action_option in action._actions
        for option in action_option.option_strings
    } | {option for action in parser._actions for option in action.option_strings}
    assert not {o for o in options if re.search(r"url|host|base|mirror|origin|server", o)}, options


def test_no_other_host_appears_in_the_source() -> None:
    """The last way: whatever the code does with them, these are the only hosts in it."""
    urls: set[str] = set()
    for source in PACKAGE.glob("*.py"):
        urls |= set(re.findall(r"https?://[A-Za-z0-9.\[\]:-]+", source.read_text(encoding="utf-8")))
    assert urls == {
        "https://loremfile.dev",
        "http://127.0.0.1:",
        "http://localhost:",
        "http://[::1]:",
    }, urls


def test_the_client_imports_nothing_but_the_standard_library() -> None:
    """Zero dependencies is a promise in the README and in pyproject; this is what keeps
    it true. Named modules, not a count: a new import is a decision."""
    allowed = {
        "argparse",
        "collections",
        "dataclasses",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "sys",
        "time",
        "typing",
        "urllib",
        "loremfile_client",
        "__future__",
    }
    imported: set[str] = set()
    for source in PACKAGE.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
    assert imported, "empty-set control: the scan found the imports"
    assert imported <= allowed, imported - allowed
