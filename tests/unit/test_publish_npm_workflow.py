"""What `publish-npm.yml` may do with the tarball (docs/09 §3.8).

The trusted publisher allows `npm stage publish` only, so a workflow that drifted back to
`npm publish` would fail at the registry — on a tag, after the inspection had passed. This
catches it in the pull request, together with what the step's comment calls load-bearing: an
explicit `--provenance`, the leading `./` without which npm reads the path as a GitHub
repository, and an npm new enough to have `npm stage` at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "publish-npm.yml"
PUBLISHING = re.compile(r"\bnpm\s+(?:stage\s+)?publish\b[^\n]*")
NPM_FLOOR = re.compile(r"\bat_least npm (\d+)\.(\d+)\.(\d+)\b")
STAGE_FLOOR = (11, 15, 0)  # the first npm with `npm stage` (its changelog, 11.15.0)


def run_blocks(text: str) -> list[str]:
    document = yaml.safe_load(text)
    return [
        step["run"]
        for job in document["jobs"].values()
        for step in job.get("steps") or []
        if isinstance(step.get("run"), str)
    ]


def problems(text: str) -> list[str]:
    commands = [found for run in run_blocks(text) for found in PUBLISHING.findall(run)]
    if len(commands) != 1:
        return [f"want exactly one publishing command, found {commands}"]
    [command] = commands
    words = command.split()
    found = []
    if words[:3] != ["npm", "stage", "publish"]:
        found.append(f"{command!r} publishes directly; only `npm stage publish` may run")
    if "--provenance" not in words:
        found.append(f"{command!r} leaves --provenance to npm, which skips it silently")
    tarballs = [word for word in words if word.endswith(".tgz")]
    if len(tarballs) != 1 or not tarballs[0].startswith("./"):
        found.append(f"{command!r} must name one tarball by a ./ path")
    floors = [
        tuple(map(int, m.groups())) for run in run_blocks(text) for m in NPM_FLOOR.finditer(run)
    ]
    if not floors or min(floors) < STAGE_FLOOR:
        found.append(f"the npm floor {floors} is below 11.15.0, the first npm with `npm stage`")
    return found


def test_the_workflow_stages_the_inspected_tarball_and_publishes_nothing() -> None:
    assert problems(WORKFLOW.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    ("old", "new", "named"),
    [
        ("npm stage publish --provenance", "npm publish --provenance", "publishes directly"),
        ("publish --provenance ./dist", "publish ./dist", "--provenance"),
        ("--provenance ./dist/", "--provenance dist/", "./ path"),
        ("at_least npm 11.15.0", "at_least npm 11.5.1", "npm floor"),
    ],
)
def test_each_drift_is_caught(old: str, new: str, named: str) -> None:
    """The negative controls: each property, broken on its own, is reported by name."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"control: the workflow still says {old!r}"
    found = problems(text.replace(old, new))
    assert any(named in problem for problem in found), found


def test_a_second_publishing_command_is_caught() -> None:
    """A direct publish added beside the staged one, rather than instead of it."""
    text = WORKFLOW.read_text(encoding="utf-8")
    anchor = "        run: npm stage publish --provenance ./dist/loremfile-*.tgz\n"
    assert text.count(anchor) == 1, "control: the staging step is where this test expects it"
    extra = "      - run: npm publish ./dist/loremfile-*.tgz\n"
    [problem] = problems(text.replace(anchor, anchor + extra))
    assert "exactly one" in problem
