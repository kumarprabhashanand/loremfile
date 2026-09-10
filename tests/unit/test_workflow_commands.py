"""Every `loremfile …` a workflow runs must be a command that exists (docs/09 §3).

This guard is written from two incidents, not from theory. `tokens-due` was named by
`09` §4's `health.yml` block and had never been implemented; `infra audit` was named by
§3.2 and §3.4 and had never been written. Both were caught by reading, which works right
up until the week nobody reads. A workflow that invokes a command that does not exist
fails at 04:17 on a Sunday, and the first symptom is a scheduled job that has been red
for a month.

It checks options too, because `--mode daily` and `--inject-failure` are exactly the kind
of thing that gets renamed in the CLI and left behind in the YAML.
"""

from __future__ import annotations

import re
from pathlib import Path

import click
import pytest
import yaml

from loremfile.cli import main as cli_root

WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))

#: `${{ ... }}` can expand to a flag, a path or nothing at all. Removed before parsing
#: rather than guessed at: a false failure here would be worse than a missed option.
INTERPOLATION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)
#: Shell comments, which are prose and mention command names the way prose does — the
#: first run of this test failed on "does not contain the loremfile package".
COMMENT = re.compile(r"#.*$", re.MULTILINE)
#: Subcommand words only, and only on the same line: `\s` would swallow the next
#: line's `fi` and `git` as though they were subcommands.
INVOCATION = re.compile(r"\bloremfile((?:[ \t]+[a-z][a-z0-9-]*)+)")
OPTION = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")


def run_blocks(path: Path) -> list[str]:
    """Every `run:` script in a workflow, with interpolations removed."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    scripts: list[str] = []
    for job in (document.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if isinstance(step.get("run"), str):
                scripts.append(COMMENT.sub("", INTERPOLATION.sub(" ", step["run"])))
    return scripts


def resolve(words: list[str]) -> tuple[click.Command | None, list[str]]:
    """Walk the click tree as far as the words go; return the command and the rest."""
    command: click.Command = cli_root
    index = 0
    while index < len(words) and isinstance(command, click.Group):
        found = command.get_command(click.Context(command), words[index])
        if found is None:
            return (None, words[index:])
        command = found
        index += 1
    return (command, words[index:])


def invocations() -> list[tuple[Path, str, list[str]]]:
    found: list[tuple[Path, str, list[str]]] = []
    for path in WORKFLOWS:
        for script in run_blocks(path):
            for match in INVOCATION.finditer(script):
                words = match.group(1).split()
                tail = script[match.end() : script.find("\n", match.end()) % (len(script) + 1)]
                found.append((path, " ".join(words), OPTION.findall(tail)))
    return found


def test_the_extractor_finds_the_commands_that_are_there() -> None:
    """Negative control, and it comes first on purpose.

    Every assertion below is of the form "everything found is valid". An extractor that
    found nothing would satisfy all of them, which is the vacuous-pass shape `AGENTS.md`
    lists first. This pins that it really is reading the workflows.
    """
    names = {name for _path, name, _options in invocations()}
    assert len(names) >= 8, f"only found {sorted(names)}"
    for expected in ("verify-live", "usage", "tokens-due", "infra audit", "upload"):
        assert any(name.startswith(expected) for name in names), expected


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_command_a_workflow_runs_exists(path: Path) -> None:
    for source, name, _options in invocations():
        if source != path:
            continue
        command, leftover = resolve(name.split())
        assert command is not None, f"{path.name}: `loremfile {name}` is not a command"
        assert not isinstance(command, click.Group), (
            f"{path.name}: `loremfile {name}` stops at a group; it needs a subcommand"
        )
        for word in leftover:
            assert not word.startswith("-"), leftover


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_option_a_workflow_passes_exists(path: Path) -> None:
    for source, name, options in invocations():
        if source != path:
            continue
        command, _leftover = resolve(name.split())
        if command is None or isinstance(command, click.Group):
            continue  # reported by the test above
        declared = {opt for param in command.params for opt in param.opts}
        for option in options:
            assert option in declared, (
                f"{path.name}: `loremfile {name}` has no {option}; it accepts {sorted(declared)}"
            )
