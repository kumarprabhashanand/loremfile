"""The health workflow's verdict, and the step order it depends on.

Each check in `health.yml` swallows its own result so the others still run and each
reports to its own issue. The first control drill (2026-09-14) showed the cost of that:
an injected failure opened its issue and the run was still a green tick. A final step now
fails the run when any check reported a problem — and it only works if it is **last**.
Before the did-not-complete steps, its exit 1 would make `failure()` open "Health workflow
did not complete" on every real finding, and the `success()`-gated close would never run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "health.yml"
VERDICT = "Fail the run if any check reported a problem"
OPENER = "Open the did-not-complete issue"
CLOSER = "Close the did-not-complete issue"


def steps() -> list[dict[str, Any]]:
    return list(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["check"]["steps"])


def names() -> list[str]:
    return [str(step.get("name") or step.get("id") or "") for step in steps()]


def test_the_steps_the_ordering_rule_is_about_exist() -> None:
    """Empty-set control (AGENTS.md), first: every ordering assertion below is vacuous if
    a step was renamed and `index` is never reached."""
    for name in (VERDICT, OPENER, CLOSER):
        assert name in names(), name


def test_the_verdict_is_last_and_after_both_did_not_complete_steps() -> None:
    order = names()
    assert order[-1] == VERDICT
    assert order.index(VERDICT) > order.index(OPENER)
    assert order.index(VERDICT) > order.index(CLOSER)


def test_the_verdict_runs_after_failures_and_reads_every_check() -> None:
    step = next(s for s in steps() if s.get("name") == VERDICT)
    assert "!cancelled()" in str(step["if"])
    wired = " ".join(str(value) for value in step["env"].values())
    for check in ("verify", "cost", "rotation"):
        assert f"steps.{check}." in wired, check
    assert "exit 1" in step["run"]


def test_every_check_the_verdict_reads_records_its_state() -> None:
    by_id = {step.get("id"): step for step in steps() if step.get("id")}
    assert {"verify", "cost", "rotation"} <= set(by_id)
    assert "failed=true" in by_id["verify"]["run"]
    for check in ("cost", "rotation"):
        run = by_id[check]["run"]
        assert "state=$state" in run and "GITHUB_OUTPUT" in run, check
        # Recorded before reporting, so a reporting failure cannot hide the state.
        assert run.index("GITHUB_OUTPUT") < run.index("loremfile.gh_issue"), check


def test_the_daily_health_check_runs_full_mode_within_its_bound() -> None:
    verify = next(s for s in steps() if s.get("id") == "verify")
    assert "--mode full" in verify["run"]
    assert "--mode daily" not in verify["run"]
    # 10 minutes for the checks, plus the one 600-second wait for a deploy still publishing.
    assert "--site-retry-seconds 600" in verify["run"]
    assert verify["timeout-minutes"] == 20


def test_the_defacement_check_compares_with_a_rebuild_that_has_the_legal_values() -> None:
    order = names()
    build = next(s for s in steps() if s.get("name") == "Build the site")
    assert order.index("Build the site") < order.index("verify")
    assert "--legal-values-from-env" in build["run"]
    # Exact, not a subset: this pins which secrets reach the step. FORBIDDEN_STRINGS joins
    # the three values because the same git-grep guard reads it (docs/13 §3b).
    assert set(build["env"]) == {
        "IMPRINT_NAME",
        "IMPRINT_STREET",
        "IMPRINT_POSTAL_CITY",
        "FORBIDDEN_STRINGS",
    }
    verify = next(s for s in steps() if s.get("id") == "verify")
    assert "--site-dir build/site" in verify["run"]
