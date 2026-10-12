"""The rules both clients implement, held equal across Python and JavaScript (2026-10-12).

`client/` and `client-js/` are published separately, so each carries its own copy of every
rule: the pause between downloads, the backoff on a 429, the timeout, the loopback override,
the exit codes, and the MCP server's versions, limits, error codes and instructions.
`test_mcp_surface.py` already holds `tools.json` and the README tables together; this holds
the rest. It was written after `site.js` turned out to format sizes its own way, which left
the search box free to disagree with the page about the same file.

The JavaScript is read as text, because the toolchain image has no Node and these values are
literals. The GitHub Action is a third copy of the download rules, in shell, and its pause and
backoff are held to the same values. Its `curl --max-time 900` is not the clients' 300 s and is
not compared: curl's limit covers the whole transfer, while both clients' 300 s is a socket
that sends nothing (`urlopen(timeout=)` and Node's `timeout` option alike).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "client" / "src" / "loremfile_client"
JS = ROOT / "client-js" / "src"
ACTION = ROOT / "action" / "action.yml"


def py_constants(source: str) -> dict[str, Any]:
    """Module-level names bound to literals, tuple unpacking included."""
    found: dict[str, Any] = {}
    for node in ast.parse(source).body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        value = getattr(node, "value", None)
        if target is None or value is None:
            continue
        # `frozenset({...})` is a call, which literal_eval refuses: read the literal inside it.
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"frozenset", "set", "tuple"}
            and len(value.args) == 1
        ):
            value = value.args[0]
        if isinstance(value, ast.List | ast.Tuple) and all(
            isinstance(e, ast.Name) and e.id in found for e in value.elts
        ):
            literal = [found[e.id] for e in value.elts if isinstance(e, ast.Name)]
        else:
            try:
                literal = ast.literal_eval(value)
            except ValueError:
                continue
        if isinstance(target, ast.Name):
            found[target.id] = literal
        elif isinstance(target, ast.Tuple):
            names = [element.id for element in target.elts if isinstance(element, ast.Name)]
            found.update(zip(names, literal, strict=True))
    return found


JS_CONST = re.compile(r"^(?:export )?const ([A-Z][A-Z0-9_]*) =\s*(.+?);$", re.M | re.S)


def js_value(text: str) -> Any:
    """A JavaScript literal as Python: numbers, strings joined by +, arrays, Sets, objects."""
    text = text.strip()
    if text.startswith("new Set(") and text.endswith(")"):
        return set(js_value(text[len("new Set(") : -1]))
    if text.startswith('"') and "+" in text:
        return "".join(json.loads(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', text))
    text = re.sub(r"(?<=\d)_(?=\d)", "", text)
    text = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return json.loads(text)


def js_constants(source: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for name, text in JS_CONST.findall(source):
        names = re.fullmatch(
            r"\[\s*([A-Z][A-Z0-9_]*(?:\s*,\s*[A-Z][A-Z0-9_]*)*)\s*\]", text.strip()
        )
        if names and all(n.strip() in found for n in names.group(1).split(",")):
            found[name] = [found[n.strip()] for n in names.group(1).split(",")]
            continue
        try:
            found[name] = js_value(text)
        except json.JSONDecodeError:
            continue  # not a literal: a parsed file, a computed value
    return found


def action_rules(text: str) -> dict[str, Any]:
    """The Action's pause between files and its 429 backoff, from its shell."""
    first = re.search(r"\bpause=(\d+)\b", text)
    attempts = re.search(r"for _ in ((?:\d+ ?)+); do", text)
    between = re.search(r"^\s*sleep (\d+(?:\.\d+)?)$", text, re.M)
    assert first and attempts and between, "the Action's download loop moved; read it again"
    assert "pause=$((pause * 2))" in text, "the Action no longer doubles its pause"
    waits = len(attempts.group(1).split()) - 1
    return {
        "pause_s": float(between.group(1)),
        "backoff_s": [int(first.group(1)) * 2**step for step in range(waits)],
    }


def sources() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], str, str]:
    py = {name: py_constants((PY / f"{name}.py").read_text()) for name in ("api", "cli", "mcp")}
    js = {name: js_constants((JS / f"{name}.js").read_text()) for name in ("api", "cli", "mcp")}
    return py, js, (JS / "mcp.js").read_text(), ACTION.read_text()


def ms(seconds: float) -> int:
    return round(seconds * 1000)


def differences(
    py: dict[str, dict[str, Any]], js: dict[str, dict[str, Any]], js_mcp: str, action: str
) -> list[str]:
    """Each rule whose Python and JavaScript (or shell) copies disagree, by name."""
    pairs: list[tuple[str, Any, Any]] = [
        ("BASE_URL", py["api"]["BASE_URL"], js["api"]["BASE_URL"]),
        ("OVERRIDE", py["api"]["OVERRIDE"], js["api"]["OVERRIDE"]),
        ("LOOPBACK", list(py["api"]["LOOPBACK"]), js["api"]["LOOPBACK"]),
        # urlsplit reports an IPv6 host bare and Node's URL in brackets: one host, two spellings.
        (
            "LOOPBACK_HOSTS",
            set(py["api"]["LOOPBACK_HOSTS"]),
            {host.strip("[]") for host in js["api"]["LOOPBACK_HOSTS"]},
        ),
        ("PAUSE", ms(py["api"]["PAUSE_SECONDS"]), js["api"]["PAUSE_MS"]),
        ("BACKOFF", [ms(s) for s in py["api"]["BACKOFF_SECONDS"]], js["api"]["BACKOFF_MS"]),
        ("TIMEOUT", ms(py["api"]["TIMEOUT_SECONDS"]), js["api"]["TIMEOUT_MS"]),
        ("USER_AGENT", py["api"]["USER_AGENT"], js["api"]["USER_AGENT"]),
        ("DEFAULT_DEST", py["cli"]["DEFAULT_DEST"], js["cli"]["DEFAULT_DEST"]),
        *[
            (code, py["cli"][code], js["cli"][code])
            for code in ("OK", "FAILED", "REFUSED", "UNREACHABLE")
        ],
        *[
            (name, py["mcp"][name], js["mcp"][name])
            for name in ("MODERN", "LEGACY", "SUPPORTED", "META", "DEFAULT_LIMIT", "MAX_LIMIT")
        ],
        ("INSTRUCTIONS", py["mcp"]["INSTRUCTIONS"], js["mcp"]["INSTRUCTIONS"]),
        *[
            (f"CODES.{code}", py["mcp"][code], js["mcp"]["CODES"][code])
            for code in (
                "PARSE",
                "INVALID_REQUEST",
                "METHOD_NOT_FOUND",
                "INVALID_PARAMS",
                "INTERNAL",
            )
        ],
        (
            "CODES.UNSUPPORTED_VERSION",
            py["mcp"]["UNSUPPORTED_VERSION"],
            js["mcp"]["CODES"]["UNSUPPORTED_VERSION"],
        ),
        (
            "CACHE_MS",
            {py["mcp"]["CACHE_MS"]},
            {int(n.replace("_", "")) for n in re.findall(r"ttlMs: ([\d_]+)", js_mcp)},
        ),
    ]
    rules = action_rules(action)
    pairs += [
        ("action PAUSE", ms(py["api"]["PAUSE_SECONDS"]), ms(rules["pause_s"])),
        ("action BACKOFF", list(py["api"]["BACKOFF_SECONDS"]), rules["backoff_s"]),
    ]
    return [f"{name}: Python {a!r}, other {b!r}" for name, a, b in pairs if a != b]


def test_both_clients_and_the_action_hold_the_same_rules() -> None:
    py, js, js_mcp, action = sources()
    # Empty-set control: every rule below has to have been read from both sides.
    assert {"PAUSE_SECONDS", "BACKOFF_SECONDS", "LOOPBACK_HOSTS"} <= set(py["api"])
    assert {"PAUSE_MS", "BACKOFF_MS", "LOOPBACK_HOSTS"} <= set(js["api"])
    assert set(js["mcp"]["CODES"]) >= {"PARSE", "UNSUPPORTED_VERSION"}
    assert "ttlMs: " in js_mcp
    assert differences(py, js, js_mcp, action) == []


def test_a_rule_changed_on_one_side_is_named() -> None:
    py, js, js_mcp, action = sources()
    js["api"]["PAUSE_MS"] = 400
    js["mcp"]["MODERN"] = "2026-01-01"
    changed = differences(py, js, js_mcp.replace("ttlMs: 3_600_000", "ttlMs: 60_000", 1), action)
    assert [line.split(":")[0] for line in changed] == ["PAUSE", "MODERN", "CACHE_MS"]
    slower = action.replace("sleep 0.5", "sleep 1")
    assert [line.split(":")[0] for line in differences(py, js, js_mcp, slower)] == [
        "PAUSE",
        "MODERN",
        "action PAUSE",
    ]
