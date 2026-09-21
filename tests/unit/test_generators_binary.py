"""M3.1 `bin/`: generator, validator, negative test and determinism test.

docs/06 §13 requires all four in the same pull request, so they live together here.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

from loremfile.catalog import Catalog, Fixture
from loremfile.generators import binary
from loremfile.generators.base import GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import ValidationError, validate
from loremfile.validators.binary import validate_bin

WORKDIR = Path(tempfile.gettempdir())


def ctx(path: str) -> GeneratorContext:
    return GeneratorContext(path=path, workdir=WORKDIR)


def fixture(path: str) -> Fixture:
    return Catalog.load().by_path[path]


# --- the generators --------------------------------------------------------


@pytest.mark.parametrize("size", [0, 1, 255, 256, 1000, 100_000])
def test_shake_returns_exactly_the_requested_size(size: int) -> None:
    assert len(binary.shake(ctx("bin/x.bin"), size=size)) == size


def test_shake_is_the_stream_of_its_own_seed() -> None:
    path = "bin/1kb.bin"
    seed = hashlib.sha256(f"loremfile:{path}".encode()).digest()
    assert binary.shake(ctx(path), size=1000) == hashlib.shake_256(seed).digest(1000)


def test_shake_differs_between_fixtures() -> None:
    assert binary.shake(ctx("bin/1kb.bin"), size=64) != binary.shake(ctx("bin/10kb.bin"), size=64)


def test_patterns_are_what_they_claim() -> None:
    assert binary.zeros(ctx("bin/z.bin"), size=10) == b"\x00" * 10
    assert binary.ones(ctx("bin/o.bin"), size=10) == b"\xff" * 10
    assert binary.incrementing(ctx("bin/i.bin"), size=4) == b"\x00\x01\x02\x03"


def test_incrementing_wraps_at_256() -> None:
    data = binary.incrementing(ctx("bin/i.bin"), size=600)
    assert data[255] == 255
    assert data[256] == 0
    assert len(data) == 600


# --- determinism (run twice, identical bytes) ------------------------------


@pytest.mark.parametrize(
    ("func", "path"),
    [
        (binary.shake, "bin/1kb.bin"),
        (binary.zeros, "bin/zeros-1mb.bin"),
        (binary.ones, "bin/ones-1mb.bin"),
        (binary.incrementing, "bin/incrementing-1mb.bin"),
    ],
)
def test_running_twice_gives_identical_bytes(func, path: str) -> None:
    context = ctx(path)
    with deterministic(context.seed):
        first = func(context, size=4096)
    with deterministic(context.seed):
        second = func(context, size=4096)
    assert first == second


# --- the validator ---------------------------------------------------------


def test_validator_names_each_pattern() -> None:
    entry = fixture("bin/zeros-1mb.bin")
    assert validate_bin(b"\x00" * 100, entry, "application/octet-stream") == {"pattern": "zeros"}
    assert validate_bin(b"\xff" * 100, entry, "x")["pattern"] == "ones"
    assert validate_bin(bytes(range(256)), entry, "x")["pattern"] == "incrementing"


def test_validator_recomputes_the_shake_stream() -> None:
    entry = fixture("bin/1kb.bin")
    data = binary.shake(ctx("bin/1kb.bin"), size=1000)
    assert validate_bin(data, entry, "x") == {"pattern": "shake256"}


# --- negative tests: a corrupted input must fail ---------------------------


def test_validator_rejects_bytes_that_are_not_this_fixtures_stream() -> None:
    """The point of the check: random-looking bytes from the wrong seed must fail."""
    entry = fixture("bin/1kb.bin")
    wrong = binary.shake(ctx("bin/10kb.bin"), size=1000)
    with pytest.raises(ValidationError, match="not the SHAKE-256 stream"):
        validate_bin(wrong, entry, "x")


def test_validator_rejects_a_single_flipped_byte() -> None:
    entry = fixture("bin/1kb.bin")
    data = bytearray(binary.shake(ctx("bin/1kb.bin"), size=1000))
    data[500] ^= 0x01
    with pytest.raises(ValidationError, match="not the SHAKE-256 stream"):
        validate_bin(bytes(data), entry, "x")


def test_full_validation_rejects_the_wrong_size() -> None:
    entry = fixture("bin/1kb.bin")
    report = validate(binary.shake(ctx("bin/1kb.bin"), size=999), entry, "x")
    assert not report.ok
    assert any("size_class exact" in failure for failure in report.failures)


def test_full_validation_rejects_a_wrong_expected_pattern() -> None:
    entry = fixture("bin/zeros-1mb.bin")
    report = validate(b"\xff" * entry.nominal_bytes, entry, "x")
    assert not report.ok
    assert any("expect.pattern" in failure for failure in report.failures)


def test_full_validation_accepts_the_real_thing() -> None:
    entry = fixture("bin/1kb.bin")
    report = validate(binary.shake(ctx("bin/1kb.bin"), size=1000), entry, "x")
    assert report.ok, report.failures
