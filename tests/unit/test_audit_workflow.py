"""The audit workflow has to say what it audited.

`--json` sends the whole report to a file, and `_report_audit` suppresses its stderr
block under that flag, so before this the determinism job finished with a green tick and
no counts in the log: a run that audited 0 rows was indistinguishable from one that
audited 228 (2026-09-16, run 35135699048). These tests **run** the summary steps rather
than reading them, because a step that prints nothing passes any assertion made about its
text.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "audit.yml"
DETERMINISM = "Summarise the determinism audit"
INFRA = "Summarise the infra audit"


def steps(job: str) -> list[dict[str, Any]]:
    return list(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"][job]["steps"])


def names(job: str) -> list[str]:
    return [str(step.get("name") or step.get("id") or "") for step in steps(job)]


def script(job: str, name: str) -> str:
    return str(next(step for step in steps(job) if step.get("name") == name)["run"])


def run(
    job: str, name: str, report: object, directory: Path, filename: str
) -> subprocess.CompletedProcess[str]:
    (directory / filename).write_text(json.dumps(report), encoding="utf-8")
    # S603/S607: running the step is the point — a step that prints nothing satisfies
    # any assertion about its text. The script comes from this repository's own workflow
    # file, and bash is resolved from PATH inside the pinned image CI already runs in.
    return subprocess.run(  # noqa: S603
        ["bash", "-c", script(job, name)],  # noqa: S607
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_steps_these_tests_are_about_exist() -> None:
    """Empty-set control (AGENTS.md): every assertion below is vacuous without them."""
    assert DETERMINISM in names("determinism")
    assert INFRA in names("infra")


def test_the_determinism_summary_runs_after_the_audit_and_before_the_issue() -> None:
    order = names("determinism")
    assert order.index("audit") < order.index(DETERMINISM)
    assert order.index(DETERMINISM) < order.index("Open, update or close the determinism issue")


def test_the_determinism_report_is_kept_as_an_artifact() -> None:
    """The log line is a summary; the report itself is what a drift investigation reads."""
    uploads = [
        step
        for step in steps("determinism")
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert len(uploads) == 1, "the determinism report is uploaded exactly once"
    assert uploads[0]["with"]["path"] == "determinism.json"


def test_the_determinism_summary_prints_the_three_counts(tmp_path: Path) -> None:
    report = {"summary": {"regenerated": 228, "drifted": 0, "expected_drift": 5}}
    done = run("determinism", DETERMINISM, report, tmp_path, "determinism.json")
    assert done.returncode == 0, done.stderr
    assert "regenerated=228" in done.stdout
    assert "drifted=0" in done.stdout
    assert "expected_drift=5" in done.stdout


def test_a_zero_expected_drift_is_printed_as_the_count_it_is(tmp_path: Path) -> None:
    """The flagged rows are published and compared, so zero means they all reproduced."""
    report = {"summary": {"regenerated": 228, "drifted": 0, "expected_drift": 0}}
    done = run("determinism", DETERMINISM, report, tmp_path, "determinism.json")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "determinism audit: regenerated=228 drifted=0 expected_drift=0"


def test_a_report_without_counts_fails_the_step(tmp_path: Path) -> None:
    """The defect this guards: a scopeless report must not pass as a green tick."""
    done = run("determinism", DETERMINISM, {"ok": True, "items": []}, tmp_path, "determinism.json")
    assert done.returncode != 0
    for key in ("regenerated", "drifted", "expected_drift"):
        assert key in done.stderr, done.stderr


def test_the_infra_summary_counts_each_state_separately(tmp_path: Path) -> None:
    """A permission warning is not a failure: `url-normalization` is unreadable every run,
    and printing that as `failing=1` teaches everyone that a red number means nothing."""
    report = {
        "items": [
            {"status": "ok"},
            {"status": "ok"},
            {"status": "warning"},
            {"status": "unreadable"},
            {"status": "drift"},
        ]
    }
    done = run("infra", INFRA, report, tmp_path, "audit.json")
    assert done.returncode == 0, done.stderr
    for expected in ("checks=5", "ok=2", "warning=1", "unreadable=1", "drift=1"):
        assert expected in done.stdout, done.stdout
    assert "failing" not in done.stdout


def test_an_infra_report_without_items_fails_the_step(tmp_path: Path) -> None:
    done = run("infra", INFRA, {"ok": True}, tmp_path, "audit.json")
    assert done.returncode != 0
    assert "items" in done.stderr
