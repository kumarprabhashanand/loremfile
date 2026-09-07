"""M1.7: the determinism guard actually pins what it claims to (docs/06 §4)."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import random
import secrets
import time
import uuid

import pytest

from loremfile.config import SOURCE_DATE_EPOCH
from loremfile.util.determinism import (
    FIXED_DATETIME,
    SeededByteStream,
    assert_environment,
    deterministic,
    seed_for,
)


def sample() -> tuple[object, ...]:
    """One draw from every source the guard is supposed to control."""
    return (
        os.urandom(16),
        secrets.token_bytes(8),
        str(uuid.uuid4()),
        random.random(),
        random.randint(0, 10**9),
        random.getrandbits(64),
        time.time(),
        time.time_ns(),
        dt.datetime.now().isoformat(),
        dt.datetime.now(dt.UTC).isoformat(),
        dt.datetime.utcnow().isoformat(),
    )


def test_same_seed_gives_identical_draws() -> None:
    with deterministic(seed_for("bin/1mb.bin")):
        first = sample()
    with deterministic(seed_for("bin/1mb.bin")):
        second = sample()
    assert first == second


def test_different_paths_give_different_draws() -> None:
    with deterministic(seed_for("bin/1mb.bin")):
        first = sample()
    with deterministic(seed_for("bin/2mb.bin")):
        second = sample()
    assert first != second


def test_clocks_report_the_epoch() -> None:
    with deterministic(seed_for("x/y.bin")):
        assert time.time() == float(SOURCE_DATE_EPOCH)
        assert time.time_ns() == SOURCE_DATE_EPOCH * 1_000_000_000
        assert dt.datetime.now(dt.UTC) == FIXED_DATETIME
        assert dt.datetime.now().year == 2020
        assert dt.datetime.utcnow().isoformat() == "2020-01-01T00:00:00"


def test_datetime_arithmetic_still_works_inside_the_patch() -> None:
    """Libraries do arithmetic on now(); the subclass must behave like a datetime."""
    with deterministic(seed_for("x/y.bin")):
        later = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
        assert later.isoformat().startswith("2020-01-02")
        assert isinstance(dt.datetime.now(dt.UTC), dt.datetime)


def test_patches_are_removed_on_exit() -> None:
    with deterministic(seed_for("x/y.bin")):
        pinned = time.time()
    assert time.time() != pinned, "the clock must run again outside the block"
    assert os.urandom(8) != os.urandom(8), "urandom must be real again"


def test_patches_are_removed_even_after_an_exception() -> None:
    with pytest.raises(RuntimeError, match="boom"), deterministic(seed_for("x/y.bin")):
        raise RuntimeError("boom")
    assert time.time() != float(SOURCE_DATE_EPOCH)


def test_uuid4_is_reproducible_and_well_formed() -> None:
    with deterministic(seed_for("x/y.bin")):
        first = uuid.uuid4()
    with deterministic(seed_for("x/y.bin")):
        second = uuid.uuid4()
    assert first == second
    assert first.version == 4


def test_seed_is_sha256_of_the_prefixed_path() -> None:
    assert seed_for("pdf/a4-3pages.pdf") == hashlib.sha256(b"loremfile:pdf/a4-3pages.pdf").digest()
    assert len(seed_for("x")) == 32


# --- the byte stream -------------------------------------------------------


def test_stream_is_reproducible_and_endless() -> None:
    assert SeededByteStream(b"seed").read(1000) == SeededByteStream(b"seed").read(1000)
    assert len(SeededByteStream(b"seed").read(100_000)) == 100_000


def test_stream_is_continuous_across_reads() -> None:
    """Reading 10 then 10 must equal reading 20; otherwise buffering loses bytes."""
    split = SeededByteStream(b"seed")
    joined = SeededByteStream(b"seed")
    assert split.read(10) + split.read(10) == joined.read(20)


def test_stream_crosses_its_internal_block_boundary_cleanly() -> None:
    split = SeededByteStream(b"seed")
    joined = SeededByteStream(b"seed")
    assert split.read(4095) + split.read(4095) == joined.read(8190)


def test_stream_rejects_a_negative_size() -> None:
    with pytest.raises(ValueError, match="negative"):
        SeededByteStream(b"seed").read(-1)


def test_different_seeds_diverge() -> None:
    assert SeededByteStream(b"a").read(32) != SeededByteStream(b"b").read(32)


# --- the container environment --------------------------------------------


def test_environment_matches_the_image() -> None:
    """PYTHONHASHSEED cannot be set from inside a running interpreter, so it is the
    image's job; this asserts the image did it."""
    problems = assert_environment()
    assert not problems, "; ".join(problems)
