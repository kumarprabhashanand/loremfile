"""The two MCP servers offer one surface (client-js/src/mcp.js, client/.../mcp.py).

Each package ships its own copy of tools.json, because each is published alone; this
holds the copies byte for byte together, and the two READMEs' tool tables with them.
Each tree's own suite then checks its server against its README over real stdio.
"""

from __future__ import annotations

import re
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
