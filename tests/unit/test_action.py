"""The composite action at `action/`, and the CI job that exercises it (README).

What is pinned here is what the action promises a caller: shell only, nothing fetched from
anywhere but loremfile.dev, every file checked against the manifest, and the same path guard
`deploy.yml` uses on its own input. The CI job is pinned too, because an action that is only
ever run from a tag is an action nobody tested before publishing it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = yaml.safe_load((ROOT / "action" / "action.yml").read_text(encoding="utf-8"))
CI = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
SCRIPT = str(ACTION["runs"]["steps"][0]["run"])
JOB: dict[str, Any] = CI["jobs"]["action"]
STEPS: list[dict[str, Any]] = JOB["steps"]


def test_it_is_a_composite_action_running_bash_and_nothing_else() -> None:
    assert ACTION["runs"]["using"] == "composite"
    steps = ACTION["runs"]["steps"]
    assert len(steps) == 1, "control: the whole action is one step"
    assert steps[0]["shell"] == "bash"
    assert "uses" not in steps[0], "no third-party action"
    for banned in ("node", "npm", "npx", "python"):
        assert banned not in SCRIPT.lower(), f"the action must not reach for {banned}"


def test_it_talks_to_loremfile_and_to_loopback_only() -> None:
    """The one override exists for the tests below and accepts a loopback address only, so
    it cannot be used to point somebody's workflow at another host."""
    hosts = set(re.findall(r"https?://[A-Za-z0-9.:]+", SCRIPT))
    assert hosts == {"https://loremfile.dev", "http://127.0.0.1:", "http://localhost:"}
    assert 'echo "::error::LOREMFILE_BASE_URL accepts a loopback address only"' in SCRIPT


def test_the_inputs_and_outputs_are_the_documented_ones() -> None:
    assert set(ACTION["inputs"]) == {"paths", "formats", "dest", "verify", "catalog-version"}
    assert ACTION["inputs"]["dest"]["default"] == "loremfile-fixtures"
    assert ACTION["inputs"]["verify"]["default"] == "true"
    assert set(ACTION["outputs"]) == {"dir", "count"}


def test_the_path_guard_is_the_one_the_deploy_uses() -> None:
    deploy = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8"))
    only = next(
        str(step["run"]) for step in deploy["jobs"]["deploy"]["steps"] if step.get("id") == "only"
    )
    guard = "*[!A-Za-z0-9._/-]*|*..*|/*)"
    assert guard in only, "control: the deploy's own guard still looks like this"
    assert guard in SCRIPT


def test_every_file_is_checked_and_a_mismatch_names_it() -> None:
    assert 'got="$(digest "$out")"' in SCRIPT
    assert 'echo "::error::$path: downloaded sha256 $got, the manifest says $want"' in SCRIPT
    assert "sha256sum" in SCRIPT and "shasum -a 256" in SCRIPT, "Linux and macOS"
    assert "Windows is not supported" in SCRIPT


def test_it_is_a_polite_client_of_our_own_rate_limit() -> None:
    assert "sleep 0.5" in SCRIPT, "a pause between files"
    assert "429)" in SCRIPT and "pause=$((pause * 2))" in SCRIPT, "backoff, not a tight retry"
    assert "rate limit" in str(ACTION["description"]).lower(), "and it says so"


# --- what the docs tell people to pin ----------------------------------------------------

DOCS = ("README.md", "site/content/pages/getting-started.md")


def test_the_documented_tag_is_outside_the_release_tag_pattern() -> None:
    """`action-v1` moves when the action changes. A `v*` tag could not: `release.check_tag`
    ties those to a catalog version, the tag ruleset freezes them, and `release.yml` fires
    on them."""
    pinned = {
        pin
        for doc in DOCS
        for pin in re.findall(
            r"uses: kumarprabhashanand/loremfile/action@(\S+)",
            (ROOT / doc).read_text(encoding="utf-8"),
        )
    }
    assert pinned == {"action-v1"}, "control: both documents pin the same thing"
    assert not any(pin.startswith("v") for pin in pinned)
    release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    assert release[True]["push"]["tags"] == ["v*"], "the pattern the tag must stay out of"


def test_every_example_path_is_a_published_fixture() -> None:
    """An example that 404s teaches the reader a path that does not exist, and makes a real
    404 every time someone pastes it."""
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    published = {e["path"] for e in manifest["fixtures"] if e.get("status", "active") == "active"}
    formats = {e["format"] for e in manifest["fixtures"]}

    shape = re.compile(r"[a-z0-9]+/[a-z0-9][a-z0-9._-]*\.[a-z0-9]+")
    sources = [str(ACTION["inputs"][name]["description"]) for name in ("paths", "formats")]
    for doc in DOCS:
        sources += re.findall(r"^\s*paths: (.+)$", (ROOT / doc).read_text(encoding="utf-8"), re.M)
    examples = {path for source in sources for path in shape.findall(source)}

    assert {"pdf/minimal.pdf", "edge/zero-byte.txt", "mp4/720p-5s.mp4"} <= examples, (
        "control: the examples were found in the action and both documents"
    )
    assert examples <= published, f"not published: {sorted(examples - published)}"
    assert "svg" in formats, "the README's `formats:` example"


# --- the CI job -------------------------------------------------------------------------


def test_ci_runs_the_action_from_this_ref_on_both_runner_families() -> None:
    assert JOB["strategy"]["matrix"]["os"] == ["ubuntu-24.04", "macos-14"]
    used = [step["uses"] for step in STEPS if "uses" in step]
    assert used.count("./action") == 4, "the real pull plus the three failures"
    assert not any(u.startswith("kumarprabhashanand/loremfile") for u in used), "never a tag"


def test_ci_pulls_a_large_file_and_an_edge_case_and_checks_the_size() -> None:
    pull = next(step for step in STEPS if step.get("id") == "pull")
    paths = str(pull["with"]["paths"]).split()
    assert "mp4/10mb.mp4" in paths, "over 10 MB"
    assert any(path.startswith("edge/") for path in paths)
    assertion = next(step for step in STEPS if "files are there" in str(step.get("name", "")))
    assert "-gt 10000000" in str(assertion["run"])


def test_ci_proves_each_failure_fails_and_the_server_answered_first() -> None:
    """A refused connection would fail the hash step for the wrong reason, so the job asserts
    the loopback server answers before it points the action at it."""
    serve = next(step for step in STEPS if str(step.get("name", "")).startswith("Serve"))
    assert '"the test server never answered"; exit 1' in str(serve["run"])
    verdict = next(step for step in STEPS if "All three failed" in str(step.get("name", "")))
    for outcome in ("bad-path", "wrong-version", "bad-hash"):
        assert f"steps.{outcome}.outcome" in str(verdict["run"])
        assert next(step for step in STEPS if step.get("id") == outcome)["continue-on-error"]
