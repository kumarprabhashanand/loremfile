"""`loremfile mcp`: a Model Context Protocol server on stdio (modelcontextprotocol.io).

The sibling of client-js/src/mcp.js, decision for decision, and the same surface: both
packages carry the same `tools.json`, and a test at the repository root holds the two
copies together. Dual-era, as the 2026-07-28 specification permits: a request carrying
`io.modelcontextprotocol/protocolVersion` in `_meta` is served on its own, with no
session; an `initialize` request opens the 2025-11-25 session older clients expect.

Standard library only, like the rest of the package. The tools return URLs and metadata
and never a file's bytes: the agent, or the test it is writing, fetches the URL.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Iterable
from importlib.resources import files
from pathlib import Path
from typing import IO, Any

from loremfile_client import __version__, api

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
#: Newest first: what `server/discover` and a version error advertise.
SUPPORTED = [MODERN, LEGACY]

META = "io.modelcontextprotocol/"
DEFAULT_LIMIT = 50
MAX_LIMIT = 250
CACHE_MS = 3_600_000

PARSE, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = (
    -32700,
    -32600,
    -32601,
    -32602,
    -32603,
)
UNSUPPORTED_VERSION = -32022

SERVER_INFO = {"name": "loremfile", "version": __version__}

INSTRUCTIONS = (
    "CC0 sample files and test fixtures from loremfile.dev, each at a stable URL. Use "
    "list_fixtures to find one, describe_fixture for its size, hash and measured properties, "
    "and verify_file to check a copy on disk. The tools return URLs, never file contents."
)

#: The tool surface, shared byte for byte with the npm client (tools.json in both trees),
#: and documented in client/README.md. Read-only tools, URLs and metadata only.
TOOLS: list[dict[str, Any]] = json.loads(
    files("loremfile_client").joinpath("tools.json").read_text(encoding="utf-8")
)


#: An argument that was not given, as distinct from one given as null (which is refused).
MISSING: Any = object()


class ToolError(Exception):
    """A failure the model can act on: a tool result with `isError`, not a protocol error."""


class ProtocolError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:  # noqa: ANN401
        super().__init__(message)
        self.code = code
        self.data = data


# --- arguments ------------------------------------------------------------------------


def _only(args: Any, allowed: list[str]) -> dict[str, Any]:  # noqa: ANN401
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    unknown = [key for key in args if key not in allowed]
    if unknown:
        raise ToolError(
            f"unknown argument {', '.join(unknown)}; this tool takes {', '.join(allowed)}"
        )
    return args


def _strings(value: Any, name: str) -> list[str]:  # noqa: ANN401
    if value is MISSING:
        return []
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ToolError(f"{name} must be a list of strings")
    return items


def _whole(value: Any) -> int | None:  # noqa: ANN401
    """An integer as JavaScript reads one: 50 and 50.0, never true."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _integer(value: Any, name: str, *, low: int, high: int | None, fallback: Any) -> Any:  # noqa: ANN401
    if value is MISSING:
        return fallback
    number = _whole(value)
    if number is None or number < low or (high is not None and number > high):
        span = f"at least {low}" if high is None else f"from {low} to {high}"
        raise ToolError(f"{name} must be a whole number {span}, not {json.dumps(value)}")
    return number


def _text(value: Any, name: str) -> str:  # noqa: ANN401
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{name} is required and must be a non-empty string")
    return value


# --- the tools ------------------------------------------------------------------------


def _url(entry: dict[str, Any]) -> str:
    return f"{api.base_url()}{entry['path']}"


def _by_path(document: dict[str, Any], path: str) -> dict[str, Any]:
    for entry in api.active(document):
        if entry["path"] == path:
            return entry
    raise ToolError(
        f"no published fixture at {json.dumps(path)}; list_fixtures shows what is published"
    )


def list_fixtures(document: dict[str, Any], args: Any) -> dict[str, Any]:  # noqa: ANN401
    args = _only(args, ["format", "tag", "max_bytes", "limit", "offset"])
    formats = _strings(args.get("format", MISSING), "format")
    tags = _strings(args.get("tag", MISSING), "tag")
    max_bytes = _integer(
        args.get("max_bytes", MISSING), "max_bytes", low=0, high=None, fallback=None
    )
    limit = _integer(
        args.get("limit", MISSING), "limit", low=1, high=MAX_LIMIT, fallback=DEFAULT_LIMIT
    )
    offset = _integer(args.get("offset", MISSING), "offset", low=0, high=None, fallback=0)
    # The same filters as `loremfile list`: any of the formats, any of the tags, all three.
    matches = sorted(
        (
            e
            for e in api.active(document)
            if (not formats or e["format"] in formats)
            and (not tags or set(tags) & set(e.get("tags") or []))
            and (max_bytes is None or e["bytes"] <= max_bytes)
        ),
        key=lambda e: e["path"],
    )
    page = matches[offset : offset + limit]
    return {
        "catalog_version": str(document.get("catalog_version", "")),
        "total": len(matches),
        "offset": offset,
        "limit": limit,
        "count": len(page),
        "next_offset": offset + limit if offset + limit < len(matches) else None,
        "fixtures": [
            {
                "path": e["path"],
                "url": _url(e),
                "format": e["format"],
                "mime": e["mime"],
                "bytes": e["bytes"],
                "tags": e.get("tags") or [],
                "description": e.get("description") or "",
            }
            for e in page
        ],
    }


def describe_fixture(document: dict[str, Any], args: Any) -> dict[str, Any]:  # noqa: ANN401
    args = _only(args, ["path"])
    entry = _by_path(document, _text(args.get("path"), "path"))
    return {
        "catalog_version": str(document.get("catalog_version", "")),
        "path": entry["path"],
        "url": _url(entry),
        "format": entry["format"],
        "mime": entry["mime"],
        "bytes": entry["bytes"],
        "sha256": entry["sha256"],
        "size_class": entry.get("size_class"),
        "tags": entry.get("tags") or [],
        "description": entry.get("description") or "",
        "props": entry.get("props"),
        "added_in": entry.get("added_in"),
    }


def verify_file(document: dict[str, Any], args: Any) -> dict[str, Any]:  # noqa: ANN401
    args = _only(args, ["path", "file"])
    entry = _by_path(document, _text(args.get("path"), "path"))
    # Lexical, as Node's path.resolve is: the answer names the path the caller gave.
    file = Path(os.path.abspath(_text(args.get("file"), "file")))  # noqa: PTH100
    present = file.is_file()
    actual = api._sha256_of(file) if present else None  # this package's own helper
    if not present:
        status = "missing"
    elif actual == entry["sha256"]:
        status = "ok"
    else:
        status = "changed"
    return {
        "path": entry["path"],
        "file": str(file),
        "status": status,
        "expected_sha256": entry["sha256"],
        "actual_sha256": actual,
        "expected_bytes": entry["bytes"],
        "actual_bytes": file.stat().st_size if present else None,
    }


HANDLERS: dict[str, Callable[[dict[str, Any], Any], dict[str, Any]]] = {
    "list_fixtures": list_fixtures,
    "describe_fixture": describe_fixture,
    "verify_file": verify_file,
}


def _serialise(value: Any) -> str:  # noqa: ANN401
    """Compact and UTF-8, as JSON.stringify writes it, so both servers print alike."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# --- the protocol ---------------------------------------------------------------------


class Server:
    """One server's state: the manifest, read once, and a legacy session if one opens."""

    def __init__(self, load: Callable[[], dict[str, Any]] | None = None) -> None:
        self._load = load or api.manifest
        self._manifest: dict[str, Any] | None = None
        self._session: str | None = None

    def _published(self) -> dict[str, Any]:
        # Kept for the process; a failed read leaves nothing, so a later call can retry.
        if self._manifest is None:
            self._manifest = self._load()
        return self._manifest

    def _call_tool(self, params: Any) -> dict[str, Any]:  # noqa: ANN401
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            raise ProtocolError(INVALID_PARAMS, "tools/call needs a tool name")
        handler = HANDLERS.get(params["name"])
        if handler is None:
            raise ProtocolError(INVALID_PARAMS, f"Unknown tool: {params['name']}")
        arguments = params.get("arguments")
        try:
            structured = handler(self._published(), {} if arguments is None else arguments)
        except (ToolError, api.Refused, api.Unreachable) as exc:
            prefix = "loremfile.dev could not be read: " if isinstance(exc, api.Unreachable) else ""
            return {"content": [{"type": "text", "text": f"{prefix}{exc}"}], "isError": True}
        return {
            "content": [{"type": "text", "text": _serialise(structured)}],
            "structuredContent": structured,
        }

    def _dispatch(self, method: str, params: Any, *, modern: bool) -> dict[str, Any]:  # noqa: ANN401
        if method == "tools/list":
            if modern:
                return {"tools": TOOLS, "ttlMs": CACHE_MS, "cacheScope": "public"}
            return {"tools": TOOLS}
        if method == "tools/call":
            return self._call_tool(params)
        if method == "server/discover" and modern:
            return {
                "supportedVersions": SUPPORTED,
                "capabilities": {"tools": {}},
                "instructions": INSTRUCTIONS,
                "ttlMs": CACHE_MS,
                "cacheScope": "public",
            }
        if method == "ping" and not modern:
            return {}
        raise ProtocolError(METHOD_NOT_FOUND, f"Method not found: {method}")

    def _request(self, method: str, params: Any) -> dict[str, Any]:  # noqa: ANN401
        if method == "initialize":
            # 2025-11-25 negotiation: echo a version this server speaks, or offer its own.
            asked = params.get("protocolVersion") if isinstance(params, dict) else None
            self._session = asked if asked == LEGACY else LEGACY
            return {
                "protocolVersion": self._session,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            }
        meta = params.get("_meta") if isinstance(params, dict) else None
        version = meta.get(f"{META}protocolVersion") if isinstance(meta, dict) else None
        if isinstance(meta, dict) and f"{META}protocolVersion" in meta:
            if version not in SUPPORTED:
                raise ProtocolError(
                    UNSUPPORTED_VERSION,
                    "Unsupported protocol version",
                    {"supported": SUPPORTED, "requested": version},
                )
            if not isinstance(meta.get(f"{META}clientCapabilities"), dict):
                raise ProtocolError(
                    INVALID_PARAMS, f"_meta lacks the required {META}clientCapabilities"
                )
            result = self._dispatch(method, params, modern=version == MODERN)
            if version != MODERN:
                return result
            return {
                "resultType": "complete",
                **result,
                "_meta": {f"{META}serverInfo": SERVER_INFO},
            }
        if self._session is not None or method == "ping":
            return self._dispatch(method, params, modern=False)
        raise ProtocolError(
            INVALID_PARAMS,
            f"_meta lacks the required {META}protocolVersion; send it on every request "
            f"(protocol {MODERN}) or open a session with initialize (protocol {LEGACY})",
        )

    def handle(self, message: Any) -> dict[str, Any] | None:  # noqa: ANN401
        """The reply to one parsed message, or None when there is nothing to send."""
        if not isinstance(message, dict):
            return {
                "jsonrpc": "2.0",
                "error": {"code": INVALID_REQUEST, "message": "not a JSON-RPC object"},
            }
        if "id" not in message:
            return None  # a notification: initialized, cancelled; nothing to answer
        ident = message["id"]
        valid_id = isinstance(ident, str) or _whole(ident) is not None
        if (
            message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
            or not valid_id
        ):
            return {
                "jsonrpc": "2.0",
                "id": ident,
                "error": {"code": INVALID_REQUEST, "message": "not a JSON-RPC 2.0 request"},
            }
        try:
            return {
                "jsonrpc": "2.0",
                "id": ident,
                "result": self._request(message["method"], message.get("params")),
            }
        except ProtocolError as exc:
            error: dict[str, Any] = {"code": exc.code, "message": str(exc)}
            if exc.data is not None:
                error["data"] = exc.data
            return {"jsonrpc": "2.0", "id": ident, "error": error}
        except Exception as exc:
            # A server answers every request; one that dies takes the agent's session with it.
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": INTERNAL, "message": str(exc)}}

    def line(self, raw: bytes) -> dict[str, Any] | None:
        """The reply to one line of input, or None."""
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"jsonrpc": "2.0", "error": {"code": PARSE, "message": "Parse error"}}
        if not text.strip():
            return None
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            return {"jsonrpc": "2.0", "error": {"code": PARSE, "message": "Parse error"}}
        return self.handle(message)


def serve(
    lines: Iterable[bytes] | None = None,
    out: IO[bytes] | None = None,
    server: Server | None = None,
) -> None:
    """Serve until the input ends: one message per line in, one per line out, in order.

    Bytes in both directions, so Windows writes `\\n` rather than `\\r\\n` and no locale
    codec stands between the wire and UTF-8.
    """
    source = sys.stdin.buffer if lines is None else lines
    sink = sys.stdout.buffer if out is None else out
    current = server or Server()
    for raw in source:
        reply = current.line(raw.rstrip(b"\r\n"))
        if reply is not None:
            sink.write((_serialise(reply) + "\n").encode("utf-8"))
            sink.flush()
