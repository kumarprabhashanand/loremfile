"""Every job that reads or writes the zone's desired state runs one at a time (ADR-029).

#58 was a race, not drift: audit run 34905539807 read `http_response_headers_transform` at
22:44:46 and saw three rules, while deploy run 34905529591 applied the fourth at 22:45:16-21.
`deploy.yml` had a concurrency group; `infra.yml` and `audit.yml` had none. They now share
one, never cancel a run in progress, and leave `health.yml` and the determinism job outside.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
GROUP = "loremfile-zone"


def load(name: str) -> dict[str, Any]:
    return dict(yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8")))


def serialised() -> dict[str, Any]:
    return {
        "deploy.yml (workflow)": load("deploy.yml").get("concurrency"),
        "infra.yml (workflow)": load("infra.yml").get("concurrency"),
        "audit.yml `infra` job": load("audit.yml")["jobs"]["infra"].get("concurrency"),
    }


def test_the_three_places_that_touch_the_zone_declare_a_concurrency_block() -> None:
    """Empty-set control first: the shared-group test below would compare three `None`s
    and pass if every block had been deleted."""
    missing = [where for where, block in serialised().items() if not block]
    assert missing == [], f"no concurrency block: {missing}"


def test_they_share_one_group_and_never_cancel_a_run_in_progress() -> None:
    for where, block in serialised().items():
        assert block["group"] == GROUP, where
        assert block["cancel-in-progress"] is False, where


def test_no_queue_key_is_relied_on() -> None:
    """GitHub documents `queue`; actionlint 1.7.12 rejects it (ADR-029). Until both agree it
    is not used, and the leftover risk — a pending run replaced by a newer one — is written
    into docs/11 §7.2 instead."""
    for where, block in serialised().items():
        assert "queue" not in block, where


def test_the_determinism_job_and_health_stay_outside_the_group() -> None:
    audit = load("audit.yml")
    assert "concurrency" not in audit, "audit.yml's group must be job-level, on `infra` only"
    assert audit["jobs"]["determinism"].get("concurrency") is None
    health = load("health.yml")
    assert health.get("concurrency") is None
    for name, job in health["jobs"].items():
        assert job.get("concurrency") is None, (
            f"health.yml `{name}`: a cancelled pending health run would silence alerting"
        )
