"""Catalogue 1.9.0: four variants each for ogg, tiff and arrow, each property measured.

Every file is built twice in fresh directories and must match itself; every property that
sets a file apart is measured by a reader other than its generator, and each has a control
that hands the validator a plausible substitute and watches it refuse.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

import pyarrow
import pyarrow.ipc
import pytest
from PIL import Image

from loremfile.build import load_generators
from loremfile.catalog import Catalog
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import ValidationError, load, validate
from loremfile.validators.columnar import validate_arrow
from loremfile.validators.image import _tiff_props
from loremfile.validators.media import _ogg_pages, _ogg_structure

PATHS = (
    "ogg/flac-10s.ogg",
    "ogg/vorbis-mono-22k-10s.ogg",
    "ogg/vorbis-cover-art-10s.ogg",
    "ogg/chained-2-streams-10s.ogg",
    "tiff/lzw-640x480.tiff",
    "tiff/multipage-3pages.tiff",
    "tiff/16bit-gray-big-endian-640x480.tiff",
    "tiff/cmyk-640x480.tiff",
    "arrow/people-1000-zstd.arrow",
    "arrow/people-1000.arrows",
    "arrow/people-1000-10-batches.arrow",
    "arrow/all-types.arrow",
)
CATALOG = Catalog.load()
load_generators()
load()


def build(path: str, directory: Path, **overrides: object) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    entry = CATALOG.by_path[path]
    # A dependency is built the same way, which reproduces its published bytes; the
    # cover-art fixture reads jpg/640x480.jpg through this.
    context = GeneratorContext(
        path=path,
        workdir=directory,
        _dependency=lambda other: build(
            other, directory / "dependencies" / other.replace("/", "_")
        ),
    )
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **(entry.params | overrides))
    return out if isinstance(out, bytes) else out.read_bytes()


def check(path: str, data: bytes, mime: str | None = None):
    entry = CATALOG.by_path[path]
    return validate(data, entry, mime or CATALOG.mime_for(entry))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("catalog-1-9")
    return {path: build(path, root / str(index)) for index, path in enumerate(PATHS)}


def test_the_batch_is_twelve_files_in_three_formats() -> None:
    """Named, so a catalog edit that drops a row fails here rather than shrinking the suite."""
    assert all(path in CATALOG.by_path for path in PATHS)
    assert {path.split("/")[0] for path in PATHS} == {"ogg", "tiff", "arrow"}


@pytest.mark.container
@pytest.mark.parametrize("path", PATHS)
def test_each_variant_validates_and_reproduces_in_a_fresh_directory(path, built, tmp_path):
    report = check(path, built[path])
    assert report.ok, report.failures
    assert built[path] == build(path, tmp_path)


# --- ogg ------------------------------------------------------------------------------------


def first_chain(data: bytes) -> bytes:
    """The bytes up to the second chain's first page: what a reader that stops would keep."""
    offset, starts = 0, []
    while offset < len(data):
        if data[offset + 5] & 0x02:
            starts.append(offset)
        count = data[offset + 26]
        offset += 27 + count + sum(data[offset + 27 : offset + 27 + count])
    return data[: starts[1]]


@pytest.mark.container
def test_the_chained_file_is_two_chains_and_its_first_chain_alone_is_refused(built):
    data = built["ogg/chained-2-streams-10s.ogg"]
    structure = _ogg_structure(data)
    assert structure["chains"] == 2
    assert structure["duration_ms"] == 10_000
    assert not check("ogg/chained-2-streams-10s.ogg", first_chain(data)).ok


@pytest.mark.container
def test_the_cover_spreads_the_header_over_several_pages_and_a_plain_file_does_not(built):
    assert _ogg_structure(built["ogg/vorbis-cover-art-10s.ogg"])["header_pages"] > 2
    plain = built["ogg/vorbis-mono-22k-10s.ogg"]
    assert _ogg_structure(plain)["header_pages"] == 2
    # A Vorbis file without the comments or the cover is not the cover-art fixture.
    assert not check("ogg/vorbis-cover-art-10s.ogg", plain).ok


@pytest.mark.container
def test_flac_in_ogg_is_refused_where_vorbis_is_expected(built):
    assert not check("ogg/vorbis-mono-22k-10s.ogg", built["ogg/flac-10s.ogg"]).ok


def test_a_truncated_ogg_page_stops_the_walk() -> None:
    page = b"OggS" + bytes([0, 0x02]) + struct.pack("<qII", 0, 1, 0) + b"\0\0\0\0" + bytes([1, 50])
    with pytest.raises(ValidationError, match="truncated"):
        _ogg_pages(page + b"x" * 10)


# --- tiff -----------------------------------------------------------------------------------


@pytest.mark.container
def test_the_byte_order_and_bit_depth_are_read_from_the_file(built):
    props = _tiff_props(built["tiff/16bit-gray-big-endian-640x480.tiff"])
    assert (props["byte_order"], props["bits_per_sample"]) == ("MM", [16])
    little = io.BytesIO()
    Image.new("I;16", (640, 480)).save(little, "TIFF")
    assert _tiff_props(little.getvalue())["byte_order"] == "II"
    assert not check("tiff/16bit-gray-big-endian-640x480.tiff", little.getvalue()).ok


@pytest.mark.container
def test_an_uncompressed_tiff_is_not_the_lzw_fixture(built):
    assert _tiff_props(built["tiff/lzw-640x480.tiff"])["compression"] == "tiff_lzw"
    assert not check("tiff/lzw-640x480.tiff", built["tiff/cmyk-640x480.tiff"]).ok
    one_page = io.BytesIO()
    Image.open(io.BytesIO(built["tiff/multipage-3pages.tiff"])).save(one_page, "TIFF")
    assert not check("tiff/multipage-3pages.tiff", one_page.getvalue()).ok


@pytest.mark.container
def test_the_three_pages_differ(built):
    with Image.open(io.BytesIO(built["tiff/multipage-3pages.tiff"])) as image:
        pages = []
        for index in range(3):
            image.seek(index)
            pages.append(image.convert("RGB").tobytes())
    assert len(set(pages)) == 3


def test_a_file_without_a_tiff_byte_order_mark_is_refused() -> None:
    with pytest.raises(ValidationError, match="byte-order"):
        _tiff_props(b"\x89PNG\r\n\x1a\n")


# --- arrow ----------------------------------------------------------------------------------


@pytest.mark.container
def test_a_stream_served_as_a_file_and_a_file_served_as_a_stream_are_refused(built):
    stream, file_ = built["arrow/people-1000.arrows"], built["arrow/people-1000-zstd.arrow"]
    entry = CATALOG.by_path["arrow/people-1000.arrows"]
    assert (
        validate_arrow(stream, entry, "application/vnd.apache.arrow.stream")["ipc_format"]
        == "stream"
    )
    with pytest.raises(ValidationError, match="served as"):
        validate_arrow(stream, entry, "application/vnd.apache.arrow.file")
    with pytest.raises(ValidationError, match="served as"):
        validate_arrow(file_, entry, "application/vnd.apache.arrow.stream")


@pytest.mark.container
def test_compression_and_batches_are_measured_and_their_absence_refused(built):
    entry = CATALOG.by_path["arrow/people-1000-zstd.arrow"]
    mime = "application/vnd.apache.arrow.file"
    assert (
        validate_arrow(built["arrow/people-1000-zstd.arrow"], entry, mime)["compression"] == "zstd"
    )
    plain = built["arrow/people-1000-10-batches.arrow"]
    assert validate_arrow(plain, entry, mime)["compression"] == "none"
    assert not check("arrow/people-1000-zstd.arrow", plain).ok
    # The same rows in one batch are not the ten-batch fixture.
    one = pyarrow.BufferOutputStream()
    table = pyarrow.ipc.open_file(pyarrow.BufferReader(plain)).read_all().combine_chunks()
    with pyarrow.ipc.new_file(one, table.schema) as writer:
        writer.write_table(table)
    assert not check("arrow/people-1000-10-batches.arrow", bytes(one.getvalue())).ok


@pytest.mark.container
def test_every_column_of_the_all_types_file_holds_nulls(built):
    props = validate_arrow(
        built["arrow/all-types.arrow"],
        CATALOG.by_path["arrow/all-types.arrow"],
        "application/vnd.apache.arrow.file",
    )
    assert props["null_counts"] == [4] * 9
    assert "map<string, int32>" in props["column_types"]
    assert "decimal128(18, 2)" in props["column_types"]
