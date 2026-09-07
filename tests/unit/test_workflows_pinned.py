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
def test_container_images_are_pinned_to_digests(workflow: Path) -> None:
    floating = []
    for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
        match = CONTAINER_IMAGE.match(line)
        if not match:
            continue
        image = match.group("image").strip("\"'")
        if not DIGEST.search(image):
            floating.append(f"{workflow.name}:{number}: {image}")
    assert not floating, "job containers must name an image digest:\n  " + "\n  ".join(floating)


def test_ci_container_matches_toolchain_digest() -> None:
    """ci.yml must run in exactly the image tools/TOOLCHAIN_DIGEST names.

    toolchain.yml rewrites both when it publishes, so a mismatch means a digest bump was
    only half applied — and CI would then test against an image nobody verified.
    """
    root = Path(__file__).resolve().parents[2]
    expected = (root / "tools" / "TOOLCHAIN_DIGEST").read_text(encoding="utf-8").strip()
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    images = {
        m.group("image").strip("\"'")
        for line in ci.splitlines()
        if (m := CONTAINER_IMAGE.match(line))
    }
    assert images == {expected}, f"ci.yml runs in {images}, TOOLCHAIN_DIGEST says {expected}"
