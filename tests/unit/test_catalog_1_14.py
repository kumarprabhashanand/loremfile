"""Catalogue 1.14.0: the phase-1 video rows that were not in the launch set.

Nine files in two formats, named by `catalog/_plan.yaml` and not by subtraction. The five
that take seconds to encode are built twice in fresh directories and must match themselves;
the four that take minutes (30 s of 720p, 60 s of 1080p, 4K, 1080p VP9) are encoded by CI's
`build --new`, validated there, and held to the manifest by `manifest check`, which is a
stronger run-twice than another copy of it here. Every control builds the file without its
one declared difference and watches the validator refuse it for the property that
difference carries, and every claim a description makes is pinned to the fact behind it.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import pytest
import yaml

from loremfile.build import load_generators
from loremfile.catalog import Catalog
from loremfile.generators import media_video
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.generators.media_video import ROTATION_MATRICES, _boxes, set_rotation
from loremfile.util.determinism import deterministic
from loremfile.util.ffmpeg import alpha_plane
from loremfile.validators import load, validate
from loremfile.validators.media import _common_props, _probe

ROOT = Path(__file__).resolve().parents[2]
CATALOG = Catalog.load()
MANIFEST = {e["path"]: e for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
PLAN = yaml.safe_load((ROOT / "catalog" / "_plan.yaml").read_text(encoding="utf-8"))["rows"]
VIDEO_FORMATS = ("mp4", "webm", "mkv", "mov", "avi", "ogv", "ts", "hls")
load_generators()
load()

PATHS = (
    "mp4/720p-30s.mp4",
    "mp4/1080p-60s.mp4",
    "mp4/4k-5s.mp4",
    "mp4/square-720x720-5s.mp4",
    "mp4/60fps-720p-5s.mp4",
    "mp4/rotated-90-metadata-720p-5s.mp4",
    "webm/1080p-10s-vp9.webm",
    "webm/720p-5s-vp8.webm",
    "webm/alpha-vp9-512x512-5s.webm",
)
QUICK = (
    "mp4/square-720x720-5s.mp4",
    "mp4/60fps-720p-5s.mp4",
    "mp4/rotated-90-metadata-720p-5s.mp4",
    "webm/720p-5s-vp8.webm",
    "webm/alpha-vp9-512x512-5s.webm",
)
ROTATED = "mp4/rotated-90-metadata-720p-5s.mp4"
ALPHA = "webm/alpha-vp9-512x512-5s.webm"


def build(path: str, directory: Path, **overrides: Any) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    entry = CATALOG.by_path[path]
    context = GeneratorContext(path=path, workdir=directory)
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **(entry.params | overrides))
    return out if isinstance(out, bytes) else out.read_bytes()


def failures(path: str, data: bytes) -> list[str]:
    entry = CATALOG.by_path[path]
    return validate(data, entry, CATALOG.mime_for(entry)).failures


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("catalog-1-14")
    return {path: build(path, root / str(index)) for index, path in enumerate(QUICK)}


# --- the batch ------------------------------------------------------------------------------


def test_the_batch_is_the_video_rows_of_the_plan_that_nothing_had_built() -> None:
    """Named from the index, so a plan row dropped from the catalog, or a row added that the
    plan never had, fails here instead of shrinking the batch to whatever was catalogued."""
    plan = [f"{r['format']}/{r['name']}" for r in PLAN if r["format"] in VIDEO_FORMATS]
    assert len(plan) == 32 and set(PATHS) <= set(plan)
    before = [p for p in plan if p not in PATHS]
    assert len(before) == 23 and all(p in MANIFEST for p in before)
    assert {MANIFEST[p]["added_in"] for p in before} <= {
        "1.0.0", "1.1.0", "1.2.0", "1.10.0"
    }  # fmt: skip
    assert {p for p, e in MANIFEST.items() if e["added_in"] == "1.14.0"} == set(PATHS)
    assert {fmt: sum(p.startswith(f"{fmt}/") for p in PATHS) for fmt in ("mp4", "webm")} == {
        "mp4": 6,
        "webm": 3,
    }
    assert all(CATALOG.by_path[p].phase == 1 for p in PATHS)


@pytest.mark.container
@pytest.mark.parametrize("path", QUICK)
def test_each_quick_file_validates_and_reproduces_in_a_fresh_directory(path, built, tmp_path):
    assert failures(path, built[path]) == []
    assert built[path] == build(path, tmp_path)


def test_the_manifest_holds_what_each_name_and_description_claims() -> None:
    """Every number below is a measured prop of the published entry, never a generator
    setting: the names say 30 s, 60 s, 4K, square, 60 fps and rotated, and the manifest has
    to agree with each."""
    props = {p: MANIFEST[p]["props"] for p in PATHS}
    size = {p: (v["width"], v["height"]) for p, v in props.items()}
    assert size["mp4/720p-30s.mp4"] == (1280, 720)
    assert size["mp4/1080p-60s.mp4"] == (1920, 1080)
    assert size["mp4/4k-5s.mp4"] == (3840, 2160)
    assert size["mp4/square-720x720-5s.mp4"] == (720, 720)
    assert size["webm/1080p-10s-vp9.webm"] == (1920, 1080)
    assert size[ALPHA] == (512, 512)
    assert {p: round(v["duration_ms"] / 1000) for p, v in props.items()} == {
        "mp4/720p-30s.mp4": 30,
        "mp4/1080p-60s.mp4": 60,
        "mp4/4k-5s.mp4": 5,
        "mp4/square-720x720-5s.mp4": 5,
        "mp4/60fps-720p-5s.mp4": 5,
        ROTATED: 5,
        "webm/1080p-10s-vp9.webm": 10,
        "webm/720p-5s-vp8.webm": 5,
        ALPHA: 5,
    }
    assert {p: v["fps"] for p, v in props.items()} == {
        p: 60.0 if p == "mp4/60fps-720p-5s.mp4" else 30.0 for p in PATHS
    }
    assert props["webm/720p-5s-vp8.webm"]["vcodec"] == "vp8"
    assert props["webm/720p-5s-vp8.webm"]["acodec"] == "vorbis"
    assert props[ROTATED]["rotation"] == 90 and (
        props[ROTATED]["width"],
        props[ROTATED]["height"],
    ) == (1280, 720)
    assert props[ALPHA]["alpha"] is True and props[ALPHA]["alpha_min"] == 0
    assert all(p in MANIFEST and MANIFEST[p]["bytes"] <= 100_000_000 for p in PATHS)


def test_no_other_video_entry_gained_or_lost_a_prop() -> None:
    """New props appear only on files that have what they measure."""
    carrying = {p for p, e in MANIFEST.items() if {"rotation", "alpha"} & set(e.get("props", {}))}
    assert carrying == {ROTATED, ALPHA}
    assert "alpha_min" in MANIFEST[ALPHA]["props"] and "alpha_max" in MANIFEST[ALPHA]["props"]


@pytest.mark.container
@pytest.mark.parametrize("path", ["mp4/360p-5s.mp4", "mkv/720p-5s.mkv"])
def test_the_validators_still_measure_published_files_as_published(path, tmp_path):
    """Read through the changed `_common_props` and `make_media_validator`: a file published
    before this batch measures to exactly the props already in the manifest, so the new keys
    cost no existing entry anything."""
    entry = CATALOG.by_path[path]
    report = validate(build(path, tmp_path), entry, CATALOG.mime_for(entry))
    assert report.ok and report.props == MANIFEST[path]["props"]


# --- the controls: each file without its one difference -------------------------------------


@pytest.mark.container
def test_the_rotated_file_is_refused_without_its_matrix(tmp_path):
    flat = build(ROTATED, tmp_path, rotation=0)
    assert "expect.rotation was not measured by the validator" in failures(ROTATED, flat)


@pytest.mark.container
def test_the_picture_is_the_published_720p_5s_and_only_the_matrix_differs(tmp_path):
    """The description's claim that this is the picture of `mp4/720p-5s.mp4`: with the one
    matrix put back to the identity, the bytes are the published file's."""
    rotated = build(ROTATED, tmp_path / "rotated")
    plain = build("mp4/720p-5s.mp4", tmp_path / "plain")
    assert hashlib.sha256(plain).hexdigest() == MANIFEST["mp4/720p-5s.mp4"]["sha256"]
    assert rotated != plain and len(rotated) == len(plain)
    out = bytearray(rotated)
    moov = next(b for b in _boxes(out, 0, len(out)) if b[0] == b"moov")
    trak = next(b for b in _boxes(out, moov[1], moov[2]) if b[0] == b"trak")
    tkhd = next(b for b in _boxes(out, trak[1], trak[2]) if b[0] == b"tkhd")
    at = tkhd[1] + media_video.TKHD_MATRIX_OFFSET[out[tkhd[1]]]
    out[at : at + 36] = struct.pack(">9i", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
    assert bytes(out) == plain


@pytest.mark.container
def test_a_rotation_reads_back_as_the_clockwise_turn_it_was_written_as(tmp_path):
    """ffprobe reports the matrix counterclockwise; `rotation` turns the sign. Written as
    90, 180 and 270 it reads back as 90, 180 and 270, and unrotated it reads back as nothing."""
    for degrees in (0, 90, 180, 270):
        small = build(ROTATED, tmp_path / str(degrees), width=160, height=90, rotation=degrees)
        report = _probe(small, ".mp4")
        video = next(s for s in report["streams"] if s["codec_type"] == "video")
        props = _common_props(report)
        assert props.get("rotation") == (degrees or None)
        assert (props["width"], props["height"]) == (160, 90), "the stored frame never moves"
        assert video["codec_name"] == "h264"


@pytest.mark.container
def test_the_60_fps_square_and_vp8_files_are_refused_without_their_difference(tmp_path):
    assert "expect.fps" in " ".join(
        failures("mp4/60fps-720p-5s.mp4", build("mp4/60fps-720p-5s.mp4", tmp_path / "a", fps=30))
    )
    square = "mp4/square-720x720-5s.mp4"
    assert "expect.width" in " ".join(failures(square, build(square, tmp_path / "b", width=1280)))
    vp8 = "webm/720p-5s-vp8.webm"
    found = " ".join(failures(vp8, build(vp8, tmp_path / "c", vcodec="vp9")))
    assert "expect.vcodec" in found and "expect.acodec" in found


@pytest.mark.container
def test_the_alpha_file_is_refused_without_alpha_and_with_alpha_that_is_all_opaque(
    built, tmp_path, monkeypatch
):
    assert failures(ALPHA, built[ALPHA]) == [], "control: the real file passes"
    plain = build(ALPHA, tmp_path / "plain", alpha=False)
    assert "expect.alpha was not measured by the validator" in failures(ALPHA, plain)
    # A stream the container flags as alpha whose plane holds nothing: the flag alone would
    # pass it, which is why the plane is decoded and its extremes measured.
    opaque = ",format=yuva420p,geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='255'"
    monkeypatch.setattr(media_video, "ALPHA_RAMP", opaque)
    flagged = build(ALPHA, tmp_path / "opaque")
    found = " ".join(failures(ALPHA, flagged))
    assert "expect.alpha_min: wanted 0, measured 255" in found


@pytest.mark.container
def test_the_alpha_rises_from_the_left_edge_to_the_right_as_the_description_says(built, tmp_path):
    path = tmp_path / "alpha.webm"
    path.write_bytes(built[ALPHA])
    plane = alpha_plane(path, "vp9")
    assert len(plane) == 512 * 512
    columns = [sum(plane[x::512]) / 512 for x in range(512)]
    assert sum(columns[:8]) / 8 < 8, "transparent at the left edge"
    assert sum(columns[-8:]) / 8 > 245, "nearly opaque at the right"
    assert columns[256] > columns[128] > columns[1], "and rising between"


# --- the generator's own bytes, with no ffmpeg ----------------------------------------------


def box(name: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + name + payload


def track(
    handler: bytes, matrix: tuple[int, ...] = (0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
) -> bytes:
    tkhd = bytes(4 + 20 + 16) + struct.pack(">9i", *matrix) + bytes(8)
    hdlr = bytes(8) + handler + bytes(13)
    return box(b"trak", box(b"tkhd", tkhd) + box(b"mdia", box(b"hdlr", hdlr)))


def matrix_of(data: bytes, nth: int) -> tuple[int, ...]:
    moov = next(b for b in _boxes(data, 0, len(data)) if b[0] == b"moov")
    tkhd = [
        child
        for trak in _boxes(data, moov[1], moov[2])
        for child in _boxes(data, trak[1], trak[2])
        if child[0] == b"tkhd"
    ][nth]
    at = tkhd[1] + 40
    return struct.unpack(">9i", data[at : at + 36])


def test_set_rotation_turns_the_video_track_and_leaves_the_audio_track_and_every_offset() -> None:
    """The video track is found by its handler type: here it is second, after audio."""
    file = box(b"ftyp", b"isom" + bytes(8)) + box(b"moov", track(b"soun") + track(b"vide"))
    out = set_rotation(file, 90)
    assert len(out) == len(file) and out != file
    assert matrix_of(out, 1) == ROTATION_MATRICES[90]
    assert matrix_of(out, 0) == matrix_of(file, 0), "the audio track's matrix is untouched"
    diff = [i for i in range(len(file)) if file[i] != out[i]]
    assert diff and max(diff) - min(diff) < 36, "only the nine matrix words changed"


def test_set_rotation_refuses_what_it_cannot_place() -> None:
    video = box(b"ftyp", b"isom" + bytes(8)) + box(b"moov", track(b"vide"))
    for bad in (0, 45, 360, -90):
        with pytest.raises(ValueError, match="rotation is one of"):
            set_rotation(video, bad)
    with pytest.raises(ValueError, match="no video track"):
        set_rotation(box(b"moov", track(b"soun")), 90)
    with pytest.raises(ValueError, match="one moov box, found 0"):
        set_rotation(box(b"ftyp", bytes(8)), 90)
    with pytest.raises(ValueError, match="does not fit its parent"):
        set_rotation(struct.pack(">I", 99) + b"moov" + bytes(8), 90)
    assert matrix_of(set_rotation(video, 270), 0) == ROTATION_MATRICES[270]
