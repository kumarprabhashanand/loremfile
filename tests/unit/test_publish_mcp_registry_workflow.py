"""What `publish-mcp-registry.yml` may do (docs/09 §3.9).

It publishes the official MCP registry entry, and nothing about a release may do that for
it: dispatch only, from main, the OIDC identity on the publishing job alone, a pinned and
checksummed `mcp-publisher`, and the inspection before the login. Each property has a
negative control below that breaks it on its own and watches it named.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[2] / ".github" / "workflows" / "publish-mcp-registry.yml"
)
MAIN_ONLY = "github.ref == 'refs/heads/main'"
RELEASES = "github.com/modelcontextprotocol/registry/releases/"


def runs(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps") or [])


def problems(text: str) -> list[str]:
    document = yaml.safe_load(text)
    triggers = document.get("on", document.get(True))  # YAML 1.1 reads a bare `on` as true
    found = []
    if set(triggers or {}) != {"workflow_dispatch"}:
        found.append(f"triggers {sorted(triggers or {})}: dispatch only, never a tag or a push")
    if document.get("permissions") != {"contents": "read"}:
        found.append(f"workflow permissions {document.get('permissions')}: contents read only")
    jobs = document["jobs"]
    for name, job in jobs.items():
        if job.get("if") != MAIN_ONLY:
            found.append(f"job {name} is not restricted to main")
        text_of_job = runs(job)
        for install in [s["run"] for s in job.get("steps") or [] if RELEASES in s.get("run", "")]:
            if "latest" in install or "sha256sum -c" not in install:
                found.append(f"job {name} installs mcp-publisher unpinned or unchecked")
            elif install.index("sha256sum -c") > install.index("tar -x"):
                found.append(f"job {name} unpacks mcp-publisher before checking it")
        oidc = job.get("permissions", {}).get("id-token") == "write"
        logs_in = "login github-oidc" in text_of_job
        if oidc != logs_in:
            found.append(f"job {name}: id-token write belongs to the job that logs in, alone")
    publishing = [name for name, job in jobs.items() if "mcp-publisher publish" in runs(job)]
    if len(publishing) != 1:
        return [*found, f"want exactly one publishing job, found {publishing}"]
    [publisher] = publishing
    inspected = [name for name, job in jobs.items() if "mcp-publisher validate" in runs(job)]
    if not inspected or jobs[publisher].get("needs") not in (inspected[0], inspected):
        found.append(f"the publishing job does not wait for the inspection {inspected}")
    script = runs(jobs[publisher])
    login, publish = "mcp-publisher login github-oidc", "mcp-publisher publish"
    if login not in script or script.index(login) > script.index(publish):
        found.append("the publishing job must log in over OIDC before it publishes")
    return found


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_the_workflow_publishes_once_after_inspecting_and_only_on_dispatch() -> None:
    assert problems(text()) == []


def test_the_finder_sees_one_pinned_install_per_job() -> None:
    """The control for the install check: it holds vacuously if it finds no install step."""
    jobs = yaml.safe_load(text())["jobs"]
    installs = {
        name: [s for s in job["steps"] if RELEASES in s.get("run", "")]
        for name, job in jobs.items()
    }
    assert {name: len(found) for name, found in installs.items()} == {"inspect": 1, "publish": 1}


def test_the_inspection_checks_both_packages_and_validates() -> None:
    inspect = runs(yaml.safe_load(text())["jobs"]["inspect"])
    for needle in ("registry.npmjs.org", "pypi.org/pypi", "mcpName", "mcp-name: ", "validate"):
        assert needle in inspect, needle


@pytest.mark.parametrize(
    ("old", "new", "named"),
    [
        (
            "on:\n  workflow_dispatch:\n",
            "on:\n  workflow_dispatch:\n  push:\n    tags: [v*]\n",
            "dispatch only",
        ),
        (
            "permissions:\n  contents: read\n\nconcurrency",
            "permissions:\n  contents: read\n  id-token: write\n\nconcurrency",
            "contents read only",
        ),
        (
            "      id-token: write # the OIDC login below, and nothing else\n",
            "",
            "belongs to the job that logs in",
        ),
        ("    needs: inspect\n", "", "does not wait"),
        ("download/v${PUBLISHER_VERSION}/", "latest/download/", "unpinned or unchecked"),
    ],
)
def test_each_drift_is_caught(old: str, new: str, named: str) -> None:
    """The negative controls: each property, broken on its own, is reported by name."""
    original = text()
    assert original.count(old) >= 1, f"control: the workflow still says {old!r}"
    found = problems(original.replace(old, new, 1))
    assert any(named in problem for problem in found), found


def test_a_job_that_runs_off_main_is_caught() -> None:
    original = text()
    assert original.count(f"    if: {MAIN_ONLY}\n") == 2, "control: both jobs are guarded"
    found = problems(original.replace(f"    if: {MAIN_ONLY}\n", "", 1))
    assert any("not restricted to main" in problem for problem in found), found
