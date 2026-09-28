"""The five snippets on /docs/languages, and the job that runs them (docs/07 §5).

The page includes the files rather than quoting them, so page and code cannot drift. What
*can* drift is the set: a sixth snippet added to the page and never run, or a file quietly
dropped from the job. These two sets are asserted equal, which is the only thing standing
between a reader and a snippet nobody has executed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "site" / "content" / "pages" / "languages.md"
CI = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
JOB = CI["jobs"]["snippets"]
INCLUDED = re.compile(r"^<!-- include: (\S+) -->$", re.M)

#: The five, named. A sixth language is a decision, not a detail — and this test is where
#: it has to be made, because adding one without running it is the failure mode.
EXPECTED = {
    "examples/verify.sh",
    "examples/verify.py",
    "examples/verify.mjs",
    "examples/verify.go",
    "examples/Verify.java",
}


def included() -> set[str]:
    return set(INCLUDED.findall(PAGE.read_text(encoding="utf-8")))


def test_the_page_includes_exactly_the_five_snippets() -> None:
    assert included() == EXPECTED


def test_every_included_file_exists_and_is_not_empty() -> None:
    for relative in included():
        source = ROOT / relative
        assert source.is_file(), relative
        assert source.read_text(encoding="utf-8").strip(), f"{relative} is empty"


def test_every_snippet_is_run_by_the_job() -> None:
    """The set the job executes, read off the job rather than assumed from its name."""
    commands = " ".join(str(step.get("run", "")) for step in JOB["steps"])
    for relative in EXPECTED:
        assert Path(relative).name in commands, f"{relative} is on the page and not in CI"


def test_the_job_runs_them_from_the_examples_directory() -> None:
    assert JOB["defaults"]["run"]["working-directory"] == "examples"


def test_the_job_installs_no_runtime() -> None:
    """Preinstalled runtimes only. A setup action per language turns a page of examples
    into a matrix to maintain, and the honest response to that is a shorter page."""
    used = [str(step["uses"]) for step in JOB["steps"] if "uses" in step]
    assert used == ["actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"], used
    commands = " ".join(str(step.get("run", "")) for step in JOB["steps"])
    for installer in ("apt-get", "brew ", "setup-python", "setup-node", "setup-go", "setup-java"):
        assert installer not in commands, installer


@pytest.mark.parametrize("relative", sorted(EXPECTED))
def test_every_snippet_fetches_the_same_fixture_and_checks_its_hash(relative: str) -> None:
    """One file across five languages is what makes the comparison honest — and each must
    actually verify, not merely download."""
    body = (ROOT / relative).read_text(encoding="utf-8")
    assert "pdf/minimal.pdf" in body, relative
    assert "loremfile.dev" in body, relative
    assert re.search(r"sha256|SHA-256", body, re.IGNORECASE), f"{relative} does not hash"


def test_the_page_says_which_file_each_snippet_reads_its_hash_from() -> None:
    """Three read manifest.json and two read sha256sums.txt; a reader comparing them has
    to be told why, or they will wonder which one is canonical."""
    text = PAGE.read_text(encoding="utf-8")
    assert "both are canonical" in text
    assert "manifest.json" in text and "sha256sums.txt" in text
