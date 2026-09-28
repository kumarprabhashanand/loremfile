"""The dependency-lock guard (tools/check_lock.py, docs/09 §4).

The constraint half is pure and is tested here with its controls. The regeneration half
needs pip-compile and the network, so CI runs it for real on every job rather than a test
mocking it — and what it does *not* catch is written down in the module's docstring,
because a control showed pip-compile reproducing a hand-edited pin exactly.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_lock", ROOT / "tools" / "check_lock.py")
assert _spec and _spec.loader
check_lock = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_lock)

LOCK = """\
click==8.5.0 \\
    --hash=sha256:aaaa
    # via loremfile
pydantic==2.13.5 \\
    --hash=sha256:bbbb
    # via loremfile
"""


def test_the_repositorys_own_lock_satisfies_its_own_constraints() -> None:
    """Control first: the real files pass, so a failure below is about the input and not
    about the parser refusing everything."""
    requirements = (ROOT / "tools" / "requirements.in").read_text(encoding="utf-8")
    pinned = check_lock.pinned_versions((ROOT / "tools" / "requirements.lock").read_text())
    assert len(pinned) > 50, "empty-set control: the lock parser found the pins"
    assert check_lock.unsatisfied(requirements, pinned) == []


def test_a_floor_the_lock_does_not_reach_is_reported() -> None:
    problems = check_lock.unsatisfied("pydantic>=99.0\n", check_lock.pinned_versions(LOCK))
    assert problems == ["pydantic>=99.0 but the lock pins 2.13.5"]


def test_a_floor_the_lock_already_reaches_is_not_a_problem() -> None:
    """The case the old rule failed: Dependabot raising a floor to the pinned version."""
    assert check_lock.unsatisfied("pydantic>=2.13.5\n", check_lock.pinned_versions(LOCK)) == []


def test_a_requirement_missing_from_the_lock_is_reported() -> None:
    problems = check_lock.unsatisfied("tomli-w\n", check_lock.pinned_versions(LOCK))
    assert problems == ["tomli-w is in requirements.in and not in the lock"]


@pytest.mark.parametrize("line", ["# a comment", "", "   ", "click  # trailing note"])
def test_comments_and_blank_lines_are_not_requirements(line: str) -> None:
    assert check_lock.unsatisfied(line + "\n", check_lock.pinned_versions(LOCK)) == []


def test_names_are_compared_the_way_pypi_normalises_them() -> None:
    """`tomli_w` in one file and `tomli-w` in the other is the same package."""
    assert check_lock.unsatisfied("tomli_w\n", {"tomli-w": check_lock.Version("1.2.0")}) == []


# --- the image's inputs hash (tools/inputs-sha.sh, docs/09 §4) ---------------------------


def inputs_sha(root: Path) -> str:
    result = subprocess.run(  # noqa: S603
        [str(ROOT / "tools" / "inputs-sha.sh"), str(root)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "tools").mkdir()
    for name in ("Dockerfile", "apt-versions.txt", "requirements.lock", "smoke.sh"):
        (tmp_path / "tools" / name).write_text(f"{name} contents\n", encoding="utf-8")
    return tmp_path


def test_the_hash_is_stable_for_unchanged_inputs(tree: Path) -> None:
    """The whole point: a rebuild of the same inputs must not look like a change."""
    assert inputs_sha(tree) == inputs_sha(tree)
    assert len(inputs_sha(tree)) == 64


@pytest.mark.parametrize("name", ["Dockerfile", "apt-versions.txt", "requirements.lock"])
def test_every_input_moves_the_hash(tree: Path, name: str) -> None:
    """Named one at a time rather than counted: a file silently dropped from the script
    would leave a real change looking like a rebuild, which is the failure this guards."""
    before = inputs_sha(tree)
    (tree / "tools" / name).write_text("changed\n", encoding="utf-8")
    assert inputs_sha(tree) != before, f"{name} does not reach the hash"


def test_the_smoke_test_is_not_an_input(tree: Path) -> None:
    """It is mounted at run time, never copied into the image, so editing it changes no
    image — and must not cost a digest bump."""
    before = inputs_sha(tree)
    (tree / "tools" / "smoke.sh").write_text("changed\n", encoding="utf-8")
    assert inputs_sha(tree) == before


def test_the_dockerfile_bakes_the_hash_in_as_a_label() -> None:
    dockerfile = (ROOT / "tools" / "Dockerfile").read_text(encoding="utf-8")
    assert 'LABEL dev.loremfile.toolchain-inputs="${TOOLCHAIN_INPUTS_SHA}"' in dockerfile
    assert "ARG TOOLCHAIN_INPUTS_SHA" in dockerfile


def test_the_workflow_passes_the_hash_and_compares_it() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/toolchain.yml").read_text())
    build = workflow["jobs"]["build"]
    assert build["outputs"]["inputs_sha"] == "${{ steps.inputs.outputs.sha }}"
    assert any("tools/inputs-sha.sh" in str(step.get("run", "")) for step in build["steps"])
    push = next(s for s in build["steps"] if s.get("id") == "build")
    assert "TOOLCHAIN_INPUTS_SHA=${{ steps.inputs.outputs.sha }}" in push["with"]["build-args"]
    propose = workflow["jobs"]["propose-digest-bump"]["steps"][-1]["run"]
    assert "dev.loremfile.toolchain-inputs" in propose
    assert '"$was" = "$INPUTS_SHA"' in propose, "the label decides, not the digest"
