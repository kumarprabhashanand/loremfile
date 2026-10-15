"""The `loremfile` fixture: what it returns, when it needs the network, and that it is inert.

pytest loads the plugin in every run where the client is installed, so the property that
matters most is the one nobody would notice breaking: a suite that never asks for the
fixture must not pay for it. The subprocess tests below run a real pytest with the socket
module refused, and each has a control that watches the same guard catch the plugin.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest
from loremfile_client import api, pytest_plugin
from loremfile_client.pytest_plugin import Files

from conftest import BODIES, Handler

SMALL = BODIES["pdf/small.pdf"]


class NetworkUsed(Exception):
    pass


def no_network(path: str) -> Any:
    raise NetworkUsed(path)


def test_a_file_arrives_verified_at_a_path(server: str, tmp_path: Path) -> None:
    local = Files(tmp_path / "cache")("pdf/small.pdf")
    assert local == (tmp_path / "cache" / "files" / "pdf" / "small.pdf").resolve()
    assert local.read_bytes() == SMALL


def test_a_filled_cache_needs_no_network(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Files(tmp_path / "cache")("pdf/small.pdf")
    monkeypatch.setattr(api, "_open", no_network)
    assert Files(tmp_path / "cache")("pdf/small.pdf").read_bytes() == SMALL


def test_control_an_empty_cache_does_need_it(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "_open", no_network)
    with pytest.raises(NetworkUsed):
        Files(tmp_path / "cache")("pdf/small.pdf")


def test_a_path_the_cached_copy_lacks_refreshes_it_once(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cache"
    Files(root)("pdf/small.pdf")
    # A cached copy from before svg/square.svg was published.
    document = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    document["fixtures"] = [e for e in document["fixtures"] if e["path"] != "svg/square.svg"]
    (root / "manifest.json").write_text(json.dumps(document), encoding="utf-8")
    fetched: list[int] = []
    real = api.manifest
    monkeypatch.setattr(api, "manifest", lambda **kw: fetched.append(1) or real(**kw))

    get = Files(root)
    assert get("svg/square.svg").read_bytes() == BODIES["svg/square.svg"]
    with pytest.raises(api.Refused, match=re.escape("not published: pdf/not-real.pdf")):
        get("pdf/not-real.pdf")
    assert fetched == [1]


@pytest.mark.parametrize("path", ["pdf/not-real.pdf", "pdf/withdrawn.pdf"])
def test_an_unpublished_or_removed_path_is_refused(server: str, tmp_path: Path, path: str) -> None:
    with pytest.raises(api.Refused, match=re.escape(f"not published: {path}")):
        Files(tmp_path / "cache")(path)


def test_bytes_that_do_not_match_are_never_returned(server: str, tmp_path: Path) -> None:
    Handler.corrupt = {"pdf/small.pdf"}
    with pytest.raises(api.Mismatch):
        Files(tmp_path / "cache")("pdf/small.pdf")
    assert not (tmp_path / "cache" / "files" / "pdf" / "small.pdf").exists()


def test_a_cached_file_that_changed_is_fetched_again(server: str, tmp_path: Path) -> None:
    root = tmp_path / "cache"
    Files(root)("pdf/small.pdf").write_bytes(b"edited by someone")
    assert Files(root)("pdf/small.pdf").read_bytes() == SMALL


def test_a_rename_another_worker_won_is_accepted(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = api.download

    def raced(entry: dict[str, Any], dest: Path, *, force: bool = False) -> api.Result:
        real(entry, dest, force=force)
        raise PermissionError("the file is open in another process")

    monkeypatch.setattr(api, "download", raced)
    assert Files(tmp_path / "cache")("pdf/small.pdf").read_bytes() == SMALL


def test_control_a_failed_rename_with_nothing_verified_is_raised(
    server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(entry: dict[str, Any], dest: Path, *, force: bool = False) -> api.Result:
        raise PermissionError("the file is open in another process")

    monkeypatch.setattr(api, "download", failed)
    with pytest.raises(PermissionError):
        Files(tmp_path / "cache")("pdf/small.pdf")


def test_the_plugin_adds_no_hooks() -> None:
    assert [name for name in vars(pytest_plugin) if name.startswith("pytest_")] == []
    assert callable(pytest_plugin.loremfile), "control: the module read is the plugin"


def test_the_client_imports_without_pytest() -> None:
    """The CLI and the MCP server must not drag pytest in; the control proves the probe sees it."""
    probe = (
        "import sys, {}; print(sorted(m for m in sys.modules"
        " if m.split('.')[0] == 'pytest' or m.endswith('pytest_plugin')))"
    )
    client = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", probe.format("loremfile_client.cli, loremfile_client.mcp")],
        capture_output=True,
        text=True,
        check=True,
    )
    assert client.stdout.strip() == "[]"
    control = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", probe.format("loremfile_client.pytest_plugin")],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "'pytest'" in control.stdout


# --- a real pytest, in a subprocess, with the network refused --------------------------

#: Installed before pytest starts, so it is in place when the plugin is imported.
GUARD = """
import json, os, socket, sys
attempts = []
def refuse(*args, **kwargs):
    attempts.append(repr(args[:2]))
    raise OSError("network refused by the test")
socket.socket.connect = refuse
socket.create_connection = refuse
socket.getaddrinfo = refuse
import pytest
code = pytest.main(sys.argv[1:])
with open(os.environ["GUARD_LOG"], "w") as log:
    json.dump(attempts, log)
sys.exit(code)
"""

USES_IT = """
def test_it(loremfile):
    assert loremfile("pdf/small.pdf").read_bytes() == b"%PDF-1.4 pretend\\n"
"""

IGNORES_IT = """
def test_it(request):
    assert request.config.pluginmanager.get_plugin("loremfile") is not None
"""


def entry_point_installed() -> None:
    """Fails rather than skips: an inertness test that quietly does not run proves nothing."""
    found = [ep.value for ep in metadata.entry_points(group="pytest11") if ep.name == "loremfile"]
    assert found == ["loremfile_client.pytest_plugin"], (
        f"pytest11 entry points named loremfile: {found}; install the client's wheel first"
    )


def pytest_run(
    where: Path, source: str, *args: str, guarded: bool = False
) -> tuple[int, list[str]]:
    entry_point_installed()
    (where / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (where / "test_it.py").write_text(source, encoding="utf-8")
    log = where / "attempts.json"
    env = {**os.environ, "GUARD_LOG": str(log)}
    env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    env.pop("PYTEST_ADDOPTS", None)
    if guarded:
        command = [sys.executable, "-c", GUARD, "-q", *args]
    else:
        command = [sys.executable, "-m", "pytest", "-q", *args]
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        command, cwd=where, env=env, capture_output=True, text=True, timeout=120, check=False
    )
    attempts = json.loads(log.read_text(encoding="utf-8")) if guarded else []
    assert done.returncode in (0, 1), done.stdout + done.stderr
    return done.returncode, attempts


def test_a_suite_that_never_asks_for_it_pays_nothing(tmp_path: Path) -> None:
    code, attempts = pytest_run(tmp_path, IGNORES_IT, guarded=True)
    assert (code, attempts) == (0, [])
    assert not (tmp_path / ".pytest_cache" / "d" / "loremfile").exists()


def test_control_the_guard_sees_the_plugin_reach_out(server: str, tmp_path: Path) -> None:
    code, attempts = pytest_run(tmp_path, USES_IT, guarded=True)
    assert code == 1
    assert attempts, "the guard recorded nothing, so the test above could not have failed"


def test_once_the_cache_is_filled_the_suite_runs_offline(server: str, tmp_path: Path) -> None:
    assert pytest_run(tmp_path, USES_IT) == (0, [])
    # Where the README tells CI to cache, and the path the inertness test finds absent.
    cached = tmp_path / ".pytest_cache" / "d" / "loremfile" / "files" / "pdf" / "small.pdf"
    assert cached.read_bytes() == SMALL
    assert pytest_run(tmp_path, USES_IT, guarded=True) == (0, [])
    # Control: the same offline run with the cache cleared has to reach out, and fails.
    code, attempts = pytest_run(tmp_path, USES_IT, "--cache-clear", guarded=True)
    assert code == 1
    assert attempts


def test_without_the_cache_provider_it_still_works(server: str, tmp_path: Path) -> None:
    assert pytest_run(tmp_path, USES_IT, "-p", "no:cacheprovider") == (0, [])
