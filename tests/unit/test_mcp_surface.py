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


def entry_problems(entry: dict, npm: str, pypi: str) -> list[str]:
    """What is wrong with an entry given the versions the two trees are at."""
    by_registry = {p["registryType"]: p for p in entry["packages"]}
    problems = []
    if set(by_registry) != {"npm", "pypi"}:
        return [f"the entry lists {sorted(by_registry)}, not npm and pypi"]
    if by_registry["npm"]["version"] != entry["version"]:
        problems.append("the entry's version is the npm package's, the one it points at")
    if release(by_registry["npm"]["version"]) > release(npm):
        problems.append(f"npm names {by_registry['npm']['version']} and the tree is at {npm}")
    if release(by_registry["pypi"]["version"]) > release(pypi):
        problems.append(f"PyPI names {by_registry['pypi']['version']} and the tree is at {pypi}")
    return problems


def test_the_entry_is_the_npm_version_and_no_package_names_a_release_its_tree_has_not_reached() -> (
    None
):
    """The entry points at the npm package, so its `version` is that package's. The PyPI package
    names a release of its own, which no longer has to match: Python 0.3.1 and npm 0.2.1 are one
    change, and 0.2.1 does not exist on PyPI. The publish workflow checks that every version the
    entry names is live and claims the name (docs/09 §3.9)."""
    npm = json.loads((ROOT / "client-js" / "package.json").read_text())["version"]
    pypi = tomllib.loads((ROOT / "client" / "pyproject.toml").read_text())["project"]["version"]
    assert entry_problems(server_json(), npm, pypi) == []


def test_the_entry_check_fires_on_each_thing_it_names() -> None:
    """Control: an entry that is wrong in each way is reported, and the real one is not."""
    entry = server_json()
    npm, pypi = "0.2.1", "0.3.1"

    def with_versions(top: str, npm_version: str, pypi_version: str) -> dict:
        packages = [
            {**p, "version": npm_version if p["registryType"] == "npm" else pypi_version}
            for p in entry["packages"]
        ]
        return {**entry, "version": top, "packages": packages}

    assert entry_problems(with_versions("0.2.1", "0.2.1", "0.2.0"), npm, pypi) == []
    assert entry_problems(with_versions("0.2.0", "0.2.1", "0.2.0"), npm, pypi), "top != npm"
    assert entry_problems(with_versions("0.2.2", "0.2.2", "0.2.0"), npm, pypi), "npm ahead of tree"
    assert entry_problems(with_versions("0.2.1", "0.2.1", "0.3.2"), npm, pypi), "PyPI ahead of tree"
    assert entry_problems({**entry, "packages": entry["packages"][:1]}, npm, pypi), "one package"


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
