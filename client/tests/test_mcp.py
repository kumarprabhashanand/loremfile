"""`loremfile mcp` against the loopback server (conftest.py): a client of each protocol era
talks to the real command over stdio, and the tool list both see must be the README's.
The sibling of client-js/test/mcp.test.js.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from loremfile_client import api, mcp

from conftest import BODIES

README = Path(__file__).resolve().parents[1] / "README.md"
META = {
    f"{mcp.META}protocolVersion": mcp.MODERN,
    f"{mcp.META}clientCapabilities": {},
    f"{mcp.META}clientInfo": {"name": "loremfile-test", "version": "0"},
}


class Client:
    """The real command as a subprocess, with a minimal JSON-RPC client on its stdio."""

    def __init__(self, base: str, cwd: Path) -> None:
        env = {**os.environ, api.OVERRIDE: base}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "loremfile_client", "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        self.lines: list[bytes] = []
        self.next = 1

    def send(self, message: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(message) + "\n").encode())
        self.proc.stdin.flush()

    def read(self) -> dict[str, Any]:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        assert line.endswith(b"\n") and not line.endswith(b"\r\n"), line
        self.lines.append(line)
        return json.loads(line)  # anything else on stdout fails the test here

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        ident, self.next = self.next, self.next + 1
        self.send(
            {
                "jsonrpc": "2.0",
                "id": ident,
                "method": method,
                **({} if params is None else {"params": params}),
            }
        )
        reply = self.read()
        assert reply["id"] == ident
        return reply

    def modern(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request(method, {**(params or {}), "_meta": META})

    def legacy(self) -> dict[str, Any]:
        reply = self.request(
            "initialize",
            {
                "protocolVersion": mcp.LEGACY,
                "capabilities": {},
                "clientInfo": {"name": "loremfile-test", "version": "0"},
            },
        )
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return reply

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        reply = self.modern("tools/call", {"name": name, "arguments": arguments})
        assert "error" not in reply, reply
        return reply["result"]

    def close(self) -> int:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        return self.proc.wait(timeout=30)


@pytest.fixture
def child(server: str, tmp_path: Path) -> Iterator[Client]:
    client = Client(server, tmp_path)
    yield client
    if client.proc.poll() is None:
        client.close()


def documented() -> dict[str, dict[str, list[str]]]:
    """The README's tool table: name, every argument, and which are required."""
    text = README.read_text(encoding="utf-8")
    section = text[text.index("## MCP server") : text.index("## What it will not do")]
    found = {}
    for row in (line for line in section.splitlines() if line.startswith("| `")):
        _, name, args, *_ = (cell.strip() for cell in row.split("|"))
        matches = re.findall(r"`([a-z_]+)`( \(required\))?", args)
        found[name.strip("`")] = {
            "args": sorted(m[0] for m in matches),
            "required": sorted(m[0] for m in matches if m[1]),
        }
    return found


def surface(tools: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    return {
        tool["name"]: {
            "args": sorted(tool["inputSchema"]["properties"]),
            "required": sorted(tool["inputSchema"].get("required", [])),
        }
        for tool in tools
    }


# --- the surface, as each era sees it ---------------------------------------------------


def test_the_readme_documents_exactly_the_three_tools() -> None:
    """The control for the comparisons below: they hold vacuously over an empty table."""
    assert list(documented()) == ["list_fixtures", "describe_fixture", "verify_file"]


def test_a_2026_07_28_client_discovers_the_server_and_lists_the_documented_tools(
    child: Client,
) -> None:
    discovered = child.modern("server/discover")["result"]
    assert discovered["resultType"] == "complete"
    assert discovered["supportedVersions"] == [mcp.MODERN, mcp.LEGACY]
    assert discovered["capabilities"] == {"tools": {}}
    assert discovered["_meta"][f"{mcp.META}serverInfo"]["name"] == "loremfile"
    listed = child.modern("tools/list")["result"]
    assert (listed["resultType"], listed["cacheScope"]) == ("complete", "public")
    assert surface(listed["tools"]) == documented()


def test_a_2025_11_25_client_initializes_and_lists_the_same_documented_tools(
    child: Client,
) -> None:
    opened = child.legacy()["result"]
    assert opened["protocolVersion"] == mcp.LEGACY
    assert opened["capabilities"] == {"tools": {}}
    assert opened["serverInfo"]["name"] == "loremfile"
    listed = child.request("tools/list")["result"]
    assert "resultType" not in listed, "a 2025-11-25 result has no resultType"
    assert surface(listed["tools"]) == documented()
    assert child.request("ping")["result"] == {}


def test_both_eras_get_identical_tool_definitions_every_one_read_only(child: Client) -> None:
    now = child.modern("tools/list")["result"]["tools"]
    child.legacy()
    assert child.request("tools/list")["result"]["tools"] == now
    for tool in now:
        assert tool["annotations"]["readOnlyHint"] is True, tool["name"]
        assert tool["annotations"]["destructiveHint"] is False, tool["name"]


def test_the_paging_bounds_the_schema_advertises_are_the_ones_enforced() -> None:
    limit = mcp.TOOLS[0]["inputSchema"]["properties"]["limit"]
    assert (limit["default"], limit["maximum"]) == (mcp.DEFAULT_LIMIT, mcp.MAX_LIMIT)


# --- versions and malformed requests: each guard, watched firing ------------------------


def test_an_unknown_version_is_refused_with_the_versions_this_server_speaks(
    child: Client,
) -> None:
    reply = child.request(
        "tools/list", {"_meta": {**META, f"{mcp.META}protocolVersion": "1999-01-01"}}
    )
    assert reply["error"]["code"] == mcp.UNSUPPORTED_VERSION
    assert reply["error"]["data"] == {"supported": mcp.SUPPORTED, "requested": "1999-01-01"}


def test_an_older_initialize_is_answered_with_2025_11_25(child: Client) -> None:
    reply = child.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
    assert reply["result"]["protocolVersion"] == mcp.LEGACY


def test_a_request_with_neither_meta_nor_a_session_is_invalid(child: Client) -> None:
    reply = child.request("tools/list")
    assert reply["error"]["code"] == mcp.INVALID_PARAMS
    assert "protocolVersion" in reply["error"]["message"]


def test_a_modern_request_without_client_capabilities_is_invalid(child: Client) -> None:
    partial = {k: v for k, v in META.items() if not k.endswith("clientCapabilities")}
    assert child.request("tools/list", {"_meta": partial})["error"]["code"] == mcp.INVALID_PARAMS


def test_unknown_methods_and_tools_are_protocol_errors_notifications_get_no_reply(
    child: Client,
) -> None:
    child.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 9}})
    assert child.modern("resources/list")["error"]["code"] == mcp.METHOD_NOT_FOUND
    assert child.modern("ping")["error"]["code"] == mcp.METHOD_NOT_FOUND, "no ping in 2026-07-28"
    unknown = child.modern("tools/call", {"name": "download_fixture", "arguments": {}})
    assert unknown["error"]["code"] == mcp.INVALID_PARAMS
    # Three requests went out after the notification and exactly three replies came back.
    assert len(child.lines) == 3


# --- the tools --------------------------------------------------------------------------


def test_list_fixtures_pages_and_says_where_it_is(child: Client, server: str) -> None:
    every = child.call("list_fixtures", {})["structuredContent"]
    assert every["total"] == 4, "the withdrawn fixture is not listed"
    assert (every["limit"], every["next_offset"]) == (mcp.DEFAULT_LIMIT, None)
    assert [f["path"] for f in every["fixtures"]] == sorted(BODIES)
    assert every["fixtures"][0]["url"] == f"{server}{sorted(BODIES)[0]}"
    first = child.call("list_fixtures", {"limit": 3})["structuredContent"]
    assert (first["count"], first["next_offset"], first["total"]) == (3, 3, 4)
    last = child.call("list_fixtures", {"limit": 3, "offset": 3})["structuredContent"]
    assert (last["count"], last["next_offset"]) == (1, None)


def test_list_fixtures_filters_as_loremfile_list_does(child: Client) -> None:
    def paths(arguments: dict[str, Any]) -> list[str]:
        result = child.call("list_fixtures", arguments)["structuredContent"]
        return [f["path"] for f in result["fixtures"]]

    assert paths({"format": ["pdf"]}) == ["pdf/other.pdf", "pdf/small.pdf"]
    assert paths({"format": "svg"}) == ["svg/square.svg"]
    assert paths({"tag": ["txt", "svg"]}) == ["svg/square.svg", "txt/notes.txt"]
    assert paths({"format": ["pdf"], "max_bytes": 17}) == ["pdf/small.pdf"]
    assert paths({"limit": 2.0}) == ["pdf/other.pdf", "pdf/small.pdf"], "50.0 is 50, as in JS"


@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": 0},
        {"limit": mcp.MAX_LIMIT + 1},
        {"offset": -1},
        {"sort": "size"},
        {"format": [1]},
        {"limit": True},
        {"format": None},
    ],
)
def test_list_fixtures_refuses_arguments_outside_its_schema(
    child: Client, arguments: dict[str, Any]
) -> None:
    assert child.call("list_fixtures", arguments)["isError"] is True


def test_every_structured_result_is_also_its_serialized_json(child: Client) -> None:
    result = child.call("describe_fixture", {"path": "pdf/small.pdf"})
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_describe_fixture_returns_the_entry_and_names_a_path_it_does_not_know(
    child: Client, server: str
) -> None:
    entry = child.call("describe_fixture", {"path": "pdf/small.pdf"})["structuredContent"]
    assert entry["bytes"] == len(BODIES["pdf/small.pdf"])
    assert entry["url"] == f"{server}pdf/small.pdf"
    assert entry["catalog_version"] == "9.9.9"
    assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
    for path in ("pdf/nope.pdf", "pdf/withdrawn.pdf"):
        missing = child.call("describe_fixture", {"path": path})
        assert missing["isError"] is True
        assert path in missing["content"][0]["text"]


def test_verify_file_reports_ok_changed_and_missing(child: Client, tmp_path: Path) -> None:
    good = tmp_path / "small.pdf"
    good.write_bytes(BODIES["pdf/small.pdf"])
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 something else\n")

    def status(file: str) -> dict[str, Any]:
        result = child.call("verify_file", {"path": "pdf/small.pdf", "file": file})
        return result["structuredContent"]

    ok = status("small.pdf")
    assert (ok["status"], ok["file"], ok["actual_sha256"]) == (
        "ok",
        str(good),
        ok["expected_sha256"],
    )
    changed = status(str(bad))
    assert changed["status"] == "changed"
    assert changed["actual_sha256"] != changed["expected_sha256"]
    assert [status("absent.pdf")["status"], status(str(tmp_path))["status"]] == [
        "missing",
        "missing",
    ]
    assert child.call("verify_file", {"path": "pdf/nope.pdf", "file": str(good)})["isError"] is True


def test_no_tool_ever_returns_a_files_bytes(child: Client, tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_bytes(BODIES["txt/notes.txt"])
    child.call("list_fixtures", {})
    for path in BODIES:
        child.call("describe_fixture", {"path": path})
    child.call("verify_file", {"path": "txt/notes.txt", "file": "notes.txt"})
    out = b"".join(child.lines)
    for path, body in BODIES.items():
        assert body.strip() not in out, path
    # The control: the same check sees the bytes when they are there.
    assert BODIES["txt/notes.txt"].strip() in out + BODIES["txt/notes.txt"]


def test_the_server_exits_cleanly_when_its_input_closes(child: Client) -> None:
    child.modern("server/discover")
    assert child.close() == 0


# --- in process -------------------------------------------------------------------------


def test_the_manifest_is_read_once_and_again_only_after_a_failed_read() -> None:
    reads = []

    def load() -> dict[str, Any]:
        reads.append(1)
        if len(reads) == 1:
            raise api.Unreachable("connection reset")
        return {"catalog_version": "1.0.0", "fixtures": []}

    server = mcp.Server(load=load)

    def ask(ident: int) -> dict[str, Any]:
        params = {"name": "list_fixtures", "arguments": {}, "_meta": META}
        reply = server.handle(
            {"jsonrpc": "2.0", "id": ident, "method": "tools/call", "params": params}
        )
        assert reply is not None
        return reply

    failed = ask(1)["result"]
    assert failed["isError"] is True
    assert "could not be read: connection reset" in failed["content"][0]["text"]
    ask(2)
    ask(3)
    assert len(reads) == 2


def test_a_line_that_is_not_json_is_a_parse_error_not_a_crash() -> None:
    reply = mcp.Server().line(b"{not json")
    assert reply is not None and reply["error"]["code"] == mcp.PARSE
