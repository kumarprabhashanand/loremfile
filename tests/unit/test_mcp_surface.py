"""The two MCP servers offer one surface (client-js/src/mcp.js, client/.../mcp.py).

Each package ships its own copy of tools.json, because each is published alone; this
holds the copies byte for byte together, and the two READMEs' tool tables with them.
Each tree's own suite then checks its server against its README over real stdio.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COPIES = (
    ROOT / "client-js" / "src" / "tools.json",
    ROOT / "client" / "src" / "loremfile_client" / "tools.json",
)
READMES = (ROOT / "client-js" / "README.md", ROOT / "client" / "README.md")


def table(readme: Path) -> str:
    found = re.search(r"\| Tool \| Arguments \| Returns \|\n(?:\|.*\|\n)+", readme.read_text())
    assert found, f"{readme} has no tool table"
    return found.group(0)


def test_both_packages_ship_the_same_tool_definitions() -> None:
    js, py = (path.read_bytes() for path in COPIES)
    assert b'"name": "describe_fixture"' in js, "control: the file holds the tools"
    assert js == py


def test_both_readmes_document_the_same_table() -> None:
    js, py = (table(readme) for readme in READMES)
    for name in ("list_fixtures", "describe_fixture", "verify_file"):
        assert f"| `{name}` |" in js, f"control: {name} is in the table"
    assert js == py


# --- the registry entry: one server, two packages ---------------------------------------


def server_json() -> dict:
    return json.loads((ROOT / "server.json").read_text())


def test_the_registry_name_is_the_one_both_packages_claim() -> None:
    """The registry checks npm's mcpName and the PyPI README's mcp-name against `name`."""
    name = server_json()["name"]
    assert name == "io.github.kumarprabhashanand/loremfile"
    assert json.loads((ROOT / "client-js" / "package.json").read_text())["mcpName"] == name
    assert f"mcp-name: {name} " in (ROOT / "client" / "README.md").read_text()


def release(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def test_the_entry_names_one_version_no_tree_is_short_of() -> None:
    """A client release that leaves the MCP server alone leaves the entry alone (docs/09
    §3.9): Python 0.3.0 added the pytest fixture and the entry still names 0.2.0. What must
    hold is that the entry is one version, and that both trees have reached it."""
    entry = server_json()
    npm = json.loads((ROOT / "client-js" / "package.json").read_text())["version"]
    pypi = tomllib.loads((ROOT / "client" / "pyproject.toml").read_text())["project"]["version"]
    by_registry = {p["registryType"]: p for p in entry["packages"]}
    assert set(by_registry) == {"npm", "pypi"}, "control: both packages are listed"
    assert by_registry["npm"]["version"] == by_registry["pypi"]["version"] == entry["version"]
    assert release(entry["version"]) <= release(npm), f"npm is at {npm}"
    assert release(entry["version"]) <= release(pypi), f"PyPI is at {pypi}"


def test_both_packages_run_the_mcp_command_on_stdio_and_nothing_is_hosted() -> None:
    entry = server_json()
    hints = {p["registryType"]: p["runtimeHint"] for p in entry["packages"]}
    assert hints == {"npm": "npx", "pypi": "uvx"}
    for package in entry["packages"]:
        assert package["identifier"] == "loremfile"
        assert package["transport"] == {"type": "stdio"}
        assert package["packageArguments"] == [{"type": "positional", "value": "mcp"}]
    assert "remotes" not in entry, "loremfile runs no hosted MCP endpoint"
    assert len(entry["description"]) <= 100, "the registry's limit"
