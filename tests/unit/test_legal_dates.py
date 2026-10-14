"""Each legal page's last-updated date: the commit that last changed its published text.

Driven against a scratch repository whose commits carry fixed dates, so every rule below is
watched both holding and failing: a change inside a page's text moves its date, a change
anywhere else in docs/13 moves nothing, and a clone without history is refused.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from loremfile.site import build

ROOT = Path(__file__).resolve().parents[2]
GIT = shutil.which("git") or "git"
CLOCK = dt.datetime(2026, 12, 31, 12, 0, tzinfo=dt.UTC)


def git(repo: Path, *args: str, when: str = "") -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else None
    subprocess.run(  # noqa: S603 - fixed argv
        [GIT, "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )


def commit(repo: Path, text: str, when: str) -> None:
    (repo / build.LEGAL_SOURCE).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", when, when=when)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """docs/13 as it is today, committed on 1 January; privacy changed on 1 February; a note
    outside every quote changed on 1 March."""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    git(root, "init", "-q")
    text = (ROOT / build.LEGAL_SOURCE).read_text(encoding="utf-8")
    commit(root, text, "2026-01-01T10:00:00+00:00")
    assert "> ## Sharing\n" in text, "the privacy section this fixture edits"
    text = text.replace("> ## Sharing\n", "> ## Sharing data\n", 1)
    commit(root, text, "2026-02-01T10:00:00+00:00")
    assert "**What changed, and why (2026-10-14).**" in text, "the note outside every quote"
    text = text.replace("**What changed, and why (2026-10-14).**", "**What changed (2026-10-14).**")
    commit(root, text, "2026-03-01T10:00:00+00:00")
    return root


def test_each_page_is_dated_by_the_commit_that_changed_its_own_text(repo: Path) -> None:
    assert build.legal_dates(repo, CLOCK) == {
        "legal/license": dt.date(2026, 1, 1),
        "legal/terms": dt.date(2026, 1, 1),
        "legal/privacy": dt.date(2026, 2, 1),
    }


def test_an_uncommitted_change_is_dated_at_the_build_clock(repo: Path) -> None:
    source = repo / build.LEGAL_SOURCE
    source.write_text(source.read_text().replace("> ## Contact\n", "> ## Contacts\n", 1))
    dates = build.legal_dates(repo, CLOCK)
    assert dates["legal/terms"] == CLOCK.date()
    assert dates["legal/privacy"] == dt.date(2026, 2, 1)


def test_the_date_is_the_utc_day_of_the_commit(repo: Path) -> None:
    text = (repo / build.LEGAL_SOURCE).read_text()
    commit(repo, text.replace("> ## Code\n", "> ## Source code\n", 1), "2026-04-01T23:30:00-02:00")
    assert build.legal_dates(repo, CLOCK)["legal/license"] == dt.date(2026, 4, 2)


def test_a_shallow_clone_is_refused_rather_than_misdated(repo: Path, tmp_path: Path) -> None:
    shallow = tmp_path / "shallow"
    subprocess.run(  # noqa: S603 - fixed argv
        [GIT, "clone", "-q", "--depth", "1", f"file://{repo}", str(shallow)],
        check=True,
        capture_output=True,
    )
    with pytest.raises(build.SiteError, match="shallow"):
        build.legal_dates(shallow, CLOCK)


def test_the_shown_date_spells_the_month_whatever_the_locale() -> None:
    line = build.updated_line(dt.date(2026, 10, 4))
    assert line == '<p>Last updated <time datetime="2026-10-04">4 October 2026</time></p>\n'


# --- every job that builds the site has the history to date it ---------------------------

WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
#: Steps that reach `build.legal_dates`: the site build itself, and the unit suite's builds.
BUILDS = ("loremfile site build", "tests/unit")


def shallow_builders(workflow: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(jobs that build the site, those among them whose checkout is shallow)."""
    building, shallow = [], []
    for name, job in (workflow.get("jobs") or {}).items():
        steps = job.get("steps") or []
        if not any(marker in str(step.get("run", "")) for step in steps for marker in BUILDS):
            continue
        building.append(name)
        checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]
        if not checkouts or any((s.get("with") or {}).get("fetch-depth") != 0 for s in checkouts):
            shallow.append(name)
    return building, shallow


def test_every_job_that_builds_the_site_fetches_full_history() -> None:
    found: dict[str, list[str]] = {}
    for path in WORKFLOWS:
        building, shallow = shallow_builders(yaml.safe_load(path.read_text(encoding="utf-8")))
        found[path.name] = building
        assert shallow == [], f"{path.name}: {shallow} build the site from a shallow clone"
    assert {"deploy", "check", "lint-and-test", "build-and-validate"} <= {
        job for jobs in found.values() for job in jobs
    }, "empty-set control: the jobs known to build the site"


def test_the_history_check_finds_a_shallow_builder() -> None:
    workflow = {
        "jobs": {
            "x": {
                "steps": [
                    {"uses": "actions/checkout@abc"},
                    {"run": "loremfile site build"},
                ]
            }
        }
    }
    assert shallow_builders(workflow) == (["x"], ["x"])
