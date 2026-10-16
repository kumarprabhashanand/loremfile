"""Neither client has a dependency, and the README and /docs/getting-started say so.

That is the most persuasive fact about adopting either package, so it is stated where a
reader looks, and this holds the statement to the two files that make it true: the first
dependency either package takes fails here, next to the sentence it would make false.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATEMENT = "**Neither has a dependency.**"
#: Every field through which an npm package can make an install pull something else in.
NPM_FIELDS = (
    "dependencies",
    "peerDependencies",
    "optionalDependencies",
    "bundleDependencies",
    "bundledDependencies",
)


def python_dependencies(pyproject: dict[str, Any]) -> list[str]:
    project = pyproject["project"]
    optional = project.get("optional-dependencies") or {}
    return [*project.get("dependencies", []), *(d for group in optional.values() for d in group)]


def npm_dependencies(package: dict[str, Any]) -> list[str]:
    return [name for field in NPM_FIELDS for name in (package.get(field) or {})]


def test_neither_package_declares_a_dependency() -> None:
    pyproject = tomllib.loads((ROOT / "client" / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "client-js" / "package.json").read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == package["name"] == "loremfile", "control: both read"
    assert python_dependencies(pyproject) == []
    assert npm_dependencies(package) == []


def test_control_a_dependency_in_either_is_caught() -> None:
    assert python_dependencies({"project": {"dependencies": ["requests"]}}) == ["requests"]
    assert python_dependencies(
        {"project": {"dependencies": [], "optional-dependencies": {"x": ["rich"]}}}
    ) == ["rich"]
    assert npm_dependencies({"peerDependencies": {"left-pad": "1"}}) == ["left-pad"]


def test_the_readme_and_getting_started_state_it() -> None:
    for page in (ROOT / "README.md", ROOT / "site" / "content" / "pages" / "getting-started.md"):
        assert STATEMENT in page.read_text(encoding="utf-8"), page
