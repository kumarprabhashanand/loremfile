"""M1.4: no floating action tags, and no floating container images, in any workflow.

A tag like ``actions/checkout@v7`` is mutable — whoever controls the tag controls what
runs with this repository's ``GITHUB_TOKEN``. Every third-party step must name a commit
SHA, and every job container must name an image digest.

This is a test rather than a one-time review so the rule keeps holding as workflows are
added in M3.1, M4.4 and M5.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

#: Any literal reference to the toolchain image, on any line.
TOOLCHAIN_LITERAL = re.compile(r"ghcr\.io/[^\s\"']*loremfile-toolchain@sha256:[0-9a-f]{64}")

WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))

USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>\S+)")
CONTAINER_IMAGE = re.compile(r"^\s*image:\s*(?P<image>\S+)")
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def test_at_least_one_workflow_exists() -> None:
    assert WORKFLOWS, "no workflows found — this test would otherwise pass vacuously"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_actions_are_pinned_to_commit_shas(workflow: Path) -> None:
    floating = []
    for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
        match = USES.match(line)
        if not match:
            continue
        ref = match.group("ref").strip("\"'")
        # ./local and docker:// forms are not tag-pinned actions.
        if ref.startswith((".", "docker://")):
            continue
        _, _, version = ref.partition("@")
        if not SHA.match(version):
            floating.append(f"{workflow.name}:{number}: {ref}")
    assert not floating, "actions must be pinned to a full commit SHA:\n  " + "\n  ".join(floating)


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_container_images_come_from_the_digest_file(workflow: Path) -> None:
    """A job container names the `setup` output, never a literal image.

    The claim being made checkable is **"tools/TOOLCHAIN_DIGEST is the only place the
    digest lives"**. It was not true until M2: `ci.yml` and `infra.yml` each carried a
    copy, `toolchain.yml` kept them in step with a `sed` over `.github/workflows/*.yml`,
    and that rewrite is what required `workflows: write` — which `GITHUB_TOKEN` does not
    have, so every digest bump was rejected with *"refusing to allow a GitHub App to
    create or update workflow .github/workflows/ci.yml"*. The duplication was invisible
    until the automation that depended on it ran.

    Without this test a future workflow reintroduces a literal and the next bump misses
    it silently — the same shape of failure as the stale `docs/09` artifact listing.
    """
    offenders = []
    for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
        match = CONTAINER_IMAGE.match(line)
        if not match:
            continue
        image = match.group("image").strip("\"'")
        if not image.startswith("${{"):
            offenders.append(f"{workflow.name}:{number}: {image}")
    assert not offenders, (
        "job containers must read tools/TOOLCHAIN_DIGEST through a `setup` job output "
        "(`${{ needs.setup.outputs.digest }}`), not name an image:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_hardcodes_the_toolchain_digest(workflow: Path) -> None:
    """Anywhere at all — not only on a `container.image` line.

    A `docker run …@sha256:…` inside a `run:` block would be just as stale after a bump
    and would not be caught by the check above.
    """
    text = workflow.read_text(encoding="utf-8")
    hits = [
        f"{workflow.name}:{number}: {line.strip()}"
        for number, line in enumerate(text.splitlines(), start=1)
        if TOOLCHAIN_LITERAL.search(line)
    ]
    assert not hits, (
        "the toolchain digest must live only in tools/TOOLCHAIN_DIGEST:\n  " + "\n  ".join(hits)
    )


def test_every_containerised_job_depends_on_setup() -> None:
    """An expression that resolves to empty is a job that silently runs on the runner.

    `needs.setup.outputs.digest` evaluates to "" in a job that does not depend on
    `setup`, and GitHub then starts the job *without* a container rather than failing.
    """
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        if "needs.setup.outputs.digest" not in text:
            continue
        document = yaml.safe_load(text)
        for name, job in (document.get("jobs") or {}).items():
            image = ((job or {}).get("container") or {}).get("image", "")
            if "needs.setup.outputs.digest" not in str(image):
                continue
            needs = job.get("needs") or []
            needs = [needs] if isinstance(needs, str) else needs
            assert "setup" in needs, (
                f"{workflow.name}: job '{name}' uses the setup output but does not "
                "depend on setup, so its container image resolves to an empty string"
            )


def test_the_digest_file_is_a_single_pinned_reference() -> None:
    root = Path(__file__).resolve().parents[2]
    digest = (root / "tools" / "TOOLCHAIN_DIGEST").read_text(encoding="utf-8").strip()
    assert "\n" not in digest
    assert DIGEST.search(digest), f"TOOLCHAIN_DIGEST is not digest-pinned: {digest}"
    assert digest.startswith("ghcr.io/"), digest


def test_the_guard_would_catch_a_reintroduced_literal() -> None:
    """Negative control. A guard nobody has seen fail is a guard nobody can trust."""
    literal = "      image: ghcr.io/kumarprabhashanand/loremfile-toolchain@sha256:" + "a" * 64
    assert TOOLCHAIN_LITERAL.search(literal), "the guard would not catch a copy-pasted digest"

    inside_a_run_block = f"          docker run --rm {literal.split('image: ')[1]} bash -lc true"
    assert TOOLCHAIN_LITERAL.search(inside_a_run_block), "a literal outside container.image"

    assert not TOOLCHAIN_LITERAL.search("      image: ${{ needs.setup.outputs.digest }}")
    assert not TOOLCHAIN_LITERAL.search("      image: ghcr.io/other/thing@sha256:" + "b" * 64)
