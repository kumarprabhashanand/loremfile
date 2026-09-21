"""Guard rails on tools/requirements.lock.

The image installs it with ``pip install --require-hashes``, which fails the whole
build if a single requirement is unpinned or unhashed. These tests assert the file is
installable *before* it reaches CI.

They exist because of a concrete incident in M1.2: a verified lock was silently
overwritten by a stale background process and the unverified file was committed. The
build only failed later, in CI. Checking the artifact itself is cheaper than trusting
that the command that produced it was the last one to write.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

LOCK = Path(__file__).resolve().parents[2] / "tools" / "requirements.lock"

# "name==version \" — pip-compile writes one of these per package, hashes underneath.
REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)==(?P<version>[^\s\\]+)")


def requirement_lines() -> list[str]:
    return [
        line
        for line in LOCK.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith((" ", "#", "--"))
    ]


def test_lock_exists() -> None:
    assert LOCK.is_file(), f"{LOCK} is missing"


def test_every_requirement_is_pinned_with_double_equals() -> None:
    unpinned = [line for line in requirement_lines() if not REQUIREMENT.match(line)]
    assert not unpinned, (
        "--require-hashes rejects requirements that are not pinned with ==:\n  "
        + "\n  ".join(unpinned)
    )


def test_no_unpinned_packages_warning() -> None:
    """pip-compile emits this block when it leaves pip/setuptools unpinned.

    Its presence means the lock was generated without --allow-unsafe and
    `pip install --require-hashes` can refuse it.
    """
    text = LOCK.read_text(encoding="utf-8")
    assert "WARNING: The following packages were not pinned" not in text, (
        "tools/requirements.lock was generated without --allow-unsafe. Regenerate with:\n"
        "  pip-compile --generate-hashes --strip-extras --allow-unsafe \\\n"
        "    --output-file=tools/requirements.lock tools/requirements.in"
    )


@pytest.mark.parametrize("package", ["pip", "setuptools", "wheel"])
def test_build_backend_packages_are_pinned(package: str) -> None:
    """pip-compile only emits these under --allow-unsafe, and pip needs them hashed."""
    names = {
        m.group("name").lower() for line in requirement_lines() if (m := REQUIREMENT.match(line))
    }
    assert package in names, f"{package} is not pinned in tools/requirements.lock"


def test_every_requirement_carries_at_least_one_hash() -> None:
    text = LOCK.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=[A-Za-z0-9._-]+==)", text)
    missing = [
        b.splitlines()[0] for b in blocks if REQUIREMENT.match(b) and "--hash=sha256:" not in b
    ]
    assert not missing, "requirements without hashes:\n  " + "\n  ".join(missing)
