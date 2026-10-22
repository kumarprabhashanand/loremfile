"""Catalogue 1.10.0: four files each for wav, mkv, parquet and pptx, each difference measured.

mkv gets three here; its fourth, VP9 and Opus in Matroska, is `expected_drift` and ships in
a pull request of its own (docs/11 §7.9b). Every file is built twice in fresh directories
and must match itself. Every control builds the same file *without* its one declared
difference and watches the validator refuse it, so a refusal can only be about that
difference, never about a duration or a size that happened to differ too.
"""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest

from loremfile.build import load_generators
from loremfile.catalog import Catalog
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.generators.media_audio import ieee_float_header
from loremfile.generators.media_video import SUBTITLE_CUES, _chapters, _srt
from loremfile.util.determinism import deterministic
from loremfile.validators import ValidationError, load, validate
from loremfile.validators.media import _info_tags, _wav_header

PATHS = (
    "wav/sine-440hz-3s-44k-32bit-float-stereo.wav",
    "wav/with-list-chunk-3s.wav",
    "wav/sine-440hz-3s-44k-8bit-stereo.wav",
    "wav/sine-440hz-3s-44k-16bit-mono.wav",
    "mkv/multi-audio-2-tracks-720p-5s.mkv",
    "mkv/with-subtitles-720p-5s.mkv",
    "mkv/with-chapters-720p-10s.mkv",
    "parquet/nested-types.parquet",
    "parquet/people-1000-zstd.parquet",
    "parquet/people-1000-gzip.parquet",
    "parquet/people-1000-10-row-groups.parquet",
    "pptx/with-chart.pptx",
    "pptx/with-table.pptx",
    "pptx/with-hidden-slide.pptx",
    "pptx/aspect-4-3-5slides.pptx",
)
CATALOG = Catalog.load()
load_generators()
load()


def build(path: str, directory: Path, **overrides: object) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    entry = CATALOG.by_path[path]
    context = GeneratorContext(path=path, workdir=directory)
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **(entry.params | overrides))
    return out if isinstance(out, bytes) else out.read_bytes()


def refused(path: str, data: bytes) -> bool:
    entry = CATALOG.by_path[path]
    return not validate(data, entry, CATALOG.mime_for(entry)).ok


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("catalog-1-10")
    return {path: build(path, root / str(index)) for index, path in enumerate(PATHS)}


def test_the_batch_is_fifteen_files_in_four_formats() -> None:
    """Named, so a catalog edit that drops a row fails here rather than shrinking the suite."""
    assert all(path in CATALOG.by_path for path in PATHS)
    counts = {fmt: sum(p.startswith(f"{fmt}/") for p in PATHS) for fmt in ("wav", "mkv")}
    assert counts == {"wav": 4, "mkv": 3}
    assert {path.split("/")[0] for path in PATHS} == {"wav", "mkv", "parquet", "pptx"}
    assert "mkv/vp9-opus-720p-5s.mkv" not in CATALOG.by_path, "it ships alone (§7.9b)"


@pytest.mark.container
@pytest.mark.parametrize("path", PATHS)
def test_each_file_validates_and_reproduces_in_a_fresh_directory(path, built, tmp_path):
    entry = CATALOG.by_path[path]
    report = validate(built[path], entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures
    assert built[path] == build(path, tmp_path)


# --- wav ------------------------------------------------------------------------------------


@pytest.mark.container
def test_the_float_file_is_tag_3_with_a_fact_chunk_and_ffmpegs_extensible_float_is_refused(
    built, tmp_path
):
    path = "wav/sine-440hz-3s-44k-32bit-float-stereo.wav"
    data = built[path]
    assert _wav_header(data) == {"header_format": "float", "header_bytes": 58}
    assert data[38:42] == b"fact", "RIFF 12 + fmt header 8 + its 18-byte body"
    # The same samples behind the header ffmpeg writes: a duplicate of the 24-bit file's case.
    extensible = REGISTRY.get("media_audio.pcm")(
        GeneratorContext(path=path, workdir=tmp_path), duration=3, bits=32, channels=2
    )
    assert _wav_header(extensible)["header_format"] == "extensible"
    assert refused(path, extensible)


@pytest.mark.container
def test_the_list_chunk_moves_the_samples_and_the_same_file_without_it_is_refused(built, tmp_path):
    path = "wav/with-list-chunk-3s.wav"
    assert _wav_header(built[path])["header_bytes"] == 94
    plain = build(path, tmp_path, info=None)
    assert _wav_header(plain) == {"header_format": "pcm", "header_bytes": 44}
    assert refused(path, plain)


@pytest.mark.container
def test_8_bit_and_mono_are_each_refused_without_their_difference(tmp_path):
    eight = "wav/sine-440hz-3s-44k-8bit-stereo.wav"
    mono = "wav/sine-440hz-3s-44k-16bit-mono.wav"
    assert refused(eight, build(eight, tmp_path / "16", bits=16))
    assert refused(mono, build(mono, tmp_path / "2", channels=2))


def wav(tag: int, fmt_size: int = 16, bits: int = 32) -> bytes:
    fmt = struct.pack("<HHIIHH", tag, 2, 44100, 44100 * 8, 8, bits) + bytes(fmt_size - 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", fmt_size) + fmt + b"data" + struct.pack("<I", 8)
    return b"RIFF" + struct.pack("<I", len(body) + 8) + body + bytes(8)


def test_the_float_rewrite_refuses_anything_but_extensible_32_bit_float() -> None:
    """Pure bytes, so it runs everywhere: a plain PCM header and a 16-bit extensible one are
    refused rather than relabelled as float."""
    with pytest.raises(ValueError, match="not an extensible 32-bit float"):
        ieee_float_header(wav(1))
    with pytest.raises(ValueError, match="not an extensible 32-bit float"):
        ieee_float_header(wav(0xFFFE, fmt_size=40, bits=16))


def test_info_tags_are_read_and_a_truncated_one_is_refused() -> None:
    body = b"INAM" + struct.pack("<I", 12) + b"Lorem ipsum\0" + b"IART" + struct.pack("<I", 9)
    body += b"Dolor Sit\0\0"  # odd size, padded to even
    assert _info_tags(body) == {"INAM": "Lorem ipsum", "IART": "Dolor Sit"}
    with pytest.raises(ValidationError, match="truncated"):
        _info_tags(b"INAM" + struct.pack("<I", 40) + b"short")


# --- mkv ------------------------------------------------------------------------------------


@pytest.mark.container
def test_each_mkv_is_refused_without_its_track_or_chapters(tmp_path):
    two = "mkv/multi-audio-2-tracks-720p-5s.mkv"
    subtitled = "mkv/with-subtitles-720p-5s.mkv"
    chaptered = "mkv/with-chapters-720p-10s.mkv"
    assert refused(two, build(two, tmp_path / "one", tones=[440]))
    assert refused(two, build(two, tmp_path / "same", tones=[440, 440])), "the tone is measured"
    assert refused(subtitled, build(subtitled, tmp_path / "bare", subtitles=False))
    assert refused(chaptered, build(chaptered, tmp_path / "flat", chapters=0))


def test_the_subtitles_and_chapters_are_written_as_their_formats_expect() -> None:
    assert _srt(SUBTITLE_CUES).startswith("1\n00:00:00,500 --> 00:00:02,000\nLorem ipsum")
    chapters = _chapters(3, 10)
    assert chapters.startswith(";FFMETADATA1\n")
    assert chapters.count("[CHAPTER]") == 3
    assert "START=6666\nEND=9999\ntitle=Chapter 3" in chapters


# --- parquet --------------------------------------------------------------------------------


@pytest.mark.container
def test_each_parquet_is_refused_without_its_difference(tmp_path):
    for path in ("parquet/people-1000-zstd.parquet", "parquet/people-1000-gzip.parquet"):
        assert refused(path, build(path, tmp_path / path.split("/")[1], compression="snappy"))
    grouped = "parquet/people-1000-10-row-groups.parquet"
    assert refused(grouped, build(grouped, tmp_path / "one-group", row_group_size=1_000_000))
    # The flat people rows are the natural substitute for the nested ones.
    flat = build("parquet/people-1000-zstd.parquet", tmp_path / "flat", compression="snappy")
    assert refused("parquet/nested-types.parquet", flat)


# --- pptx -----------------------------------------------------------------------------------


@pytest.mark.container
def test_each_deck_is_refused_without_its_difference(tmp_path):
    cases = {
        "pptx/with-chart.pptx": {"chart": False},
        "pptx/with-table.pptx": {"table_rows": 0},
        "pptx/with-hidden-slide.pptx": {"hidden": ()},
        "pptx/aspect-4-3-5slides.pptx": {"aspect": "16:9"},
    }
    for path, without in cases.items():
        assert refused(path, build(path, tmp_path / path.split("/")[1], **without)), path


@pytest.mark.container
def test_the_charts_embedded_workbook_carries_the_epoch_not_the_clock(built):
    """XlsxWriter stamps the wall clock from below the determinism guard (docs/06 §4); the
    generator pins it. Without that, two builds a minute apart differ in exactly this file."""
    with zipfile.ZipFile(io.BytesIO(built["pptx/with-chart.pptx"])) as deck:
        embedded = [n for n in deck.namelist() if n.startswith("ppt/embeddings/")]
        assert embedded == ["ppt/embeddings/Microsoft_Excel_Sheet1.xlsx"]
        workbook = zipfile.ZipFile(io.BytesIO(deck.read(embedded[0])))
    core = workbook.read("docProps/core.xml").decode()
    assert core.count("2020-01-01T00:00:00Z") == 2, core
    assert "xl/worksheets/sheet1.xml" in workbook.namelist(), "control: the data is there"
