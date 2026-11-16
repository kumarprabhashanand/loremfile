"""CI runs every npm client test and the browser search regression suite.

ci.yml names its `node --test` files one by one, so a new file that is not added there is a
suite that never runs and a job that stays green. This holds the list to the directory.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "client-js" / "test"
SITE_TESTS = ROOT / "tests" / "site"


def run_line() -> str:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    runs = [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "node --test" in str(step.get("run", ""))
    ]
    assert len(runs) == 1, f"expected one `node --test` step, found {len(runs)}"
    return runs[0]


def unlisted(files: list[str], line: str) -> list[str]:
    listed = set(re.findall(r"(?:test/|tests/site/)([\w.-]+\.test\.(?:js|cjs))", line))
    return sorted(name for name in files if name not in listed)


def test_every_client_js_test_file_runs_in_ci() -> None:
    files = sorted(path.name for path in TESTS.glob("*.test.js"))
    files += sorted(path.name for path in SITE_TESTS.glob("*.test.cjs"))
    assert {"commands.test.js", "mcp.test.js", "packaging.test.js", "search.test.cjs"} <= set(
        files
    ), "control"
    assert unlisted(files, run_line()) == []


def test_a_file_left_out_of_the_line_is_reported() -> None:
    """The control for the check above: watch it name the file that would not run."""
    line = "node --test test/commands.test.js test/packaging.test.js"
    assert unlisted(
        ["commands.test.js", "mcp.test.js", "packaging.test.js", "search.test.cjs"], line
    ) == ["mcp.test.js", "search.test.cjs"]
