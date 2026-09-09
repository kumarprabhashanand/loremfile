"""M1.7: the determinism guard actually pins what it claims to (docs/06 §4)."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import random
import re
import secrets
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from loremfile.build import fixtures_dir, load_generators
from loremfile.catalog import Catalog
from loremfile.config import SOURCE_DATE_EPOCH
from loremfile.generators.base import REGISTRY, GeneratorContext
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


# --- docs/06 §4's library determinism claims -------------------------------
#
# Every claim in that table is an assumption about a third-party library's internals.
# One of them was simply wrong — fastavro draws its sync marker from a compiled C
# extension, below the layer this guard patches — so the table is only worth anything
# if each verified row has a run-twice test standing behind it. These two tests make the
# document and the suite check each other: a verified claim with no proving fixture in
# the parametrisation fails, and a proving fixture that is not in the table fails too.

#: Proving fixtures for the rows docs/06 §4 marks verified. Adding a row to that table
#: without adding its path here fails `test_every_verified_claim_has_a_proving_test`.
PROVING_FIXTURES = [
    "avro/people-1000.avro",
    "avif/640x480.avif",
    "pdf/a4-encrypted-1page.pdf",
    "parquet/people-1000.parquet",
    "png/640x480.png",
    "sqlite/people-1000.sqlite",
    "kmz/placemarks-10.kmz",
    "docx/1page.docx",
    "xlsx/1sheet-10rows.xlsx",
    "pptx/1slide.pptx",
    "mp3/with-id3v2-tags-3s.mp3",
    "mp4/360p-5s.mp4",
]

DETERMINISM_TABLE_HEADER = "| Library | Claim | Proving fixture | Verified |"


@pytest.mark.container
@pytest.mark.parametrize("path", PROVING_FIXTURES)
def test_proving_fixture_reproduces_byte_for_byte(path: str) -> None:
    """The run-twice test that turns each verified claim into evidence.

    Marked `container` because some of these need tools that only exist in the pinned
    image — `avifenc` above all, whose single-threaded invocation is the claim.
    """
    load_generators()
    catalog = Catalog.load()
    entry = catalog.by_path[path]
    workdir = Path(tempfile.mkdtemp())

    def resolve(dependency: str) -> bytes:
        """Published bytes for a fixture this one is built from, as the build supplies."""
        source = fixtures_dir() / dependency
        if not source.is_file():
            pytest.skip(f"run `loremfile build --only {dependency}` first")
        return source.read_bytes()

    def once() -> bytes:
        context = GeneratorContext(path=path, workdir=workdir)
        context._dependency = resolve
        with deterministic(context.seed):
            out = REGISTRY.get(entry.generator)(context, **entry.params)
        return out if isinstance(out, bytes) else out.read_bytes()

    assert once() == once()


def _claim_rows() -> list[tuple[str, str, str]]:
    """(library, proving fixture path, verified cell) from docs/06 §4's table."""
    text = (Path(__file__).resolve().parents[2] / "docs" / "06-generation-pipeline.md").read_text(
        encoding="utf-8"
    )
    start = text.index(DETERMINISM_TABLE_HEADER)
    end = text.index("\n\n", start)
    rows = []
    for line in text[start:end].splitlines():
        if not line.startswith("|") or line.startswith("|---") or "| Library |" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        found = re.search(r"`([^`]+)`", cells[2])
        assert found, f"row has no proving fixture in backticks: {cells[0]}"
        rows.append((cells[0], found.group(1), cells[3]))
    return rows


def test_the_claims_table_is_present_and_populated() -> None:
    rows = _claim_rows()
    assert len(rows) >= 10, "docs/06 §4's table lost rows"


def test_every_verified_claim_has_a_proving_test() -> None:
    """A verified claim without a run-twice test is just an assertion in prose."""
    missing = [
        f"{library} -> {path}"
        for library, path, verified in _claim_rows()
        if "unverified" not in verified.lower() and path not in PROVING_FIXTURES
    ]
    assert not missing, (
        "docs/06 §4 marks these verified but no proving fixture is parametrised in "
        "PROVING_FIXTURES:\n  " + "\n  ".join(missing)
    )


def test_no_proving_fixture_is_orphaned() -> None:
    """The reverse direction: a test claiming to prove a row the table does not have."""
    paths = {path for _, path, _ in _claim_rows()}
    orphans = [path for path in PROVING_FIXTURES if path not in paths]
    assert not orphans, f"not named in docs/06 §4's table: {orphans}"


def test_unverified_claims_name_the_milestone_that_will_spike_them() -> None:
    """An unverified row has to say when it gets checked, or it never will."""
    vague = [
        library
        for library, _, verified in _claim_rows()
        if "unverified" in verified.lower() and not re.search(r"M3\.\d", verified)
    ]
    assert not vague, f"unverified without a milestone: {vague}"


def test_unverified_claims_have_no_proving_test_yet() -> None:
    """Guards against quietly marking a row verified by adding it to the list only."""
    premature = [
        f"{library} -> {path}"
        for library, path, verified in _claim_rows()
        if "unverified" in verified.lower() and path in PROVING_FIXTURES
    ]
    assert not premature, (
        "these are parametrised as proven but docs/06 §4 still says unverified — "
        "update the table in the same pull request:\n  " + "\n  ".join(premature)
    )
