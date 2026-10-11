"""What a published path's name says, held to what its bytes measure.

`jpg/cmyk-640x480.jpg` measured 640x640 from the day it was published: the catalog declared
640x640 under a 640x480 name and checked only the mode. The authoring guard in catalog.py now
catches that before publication; this one reads every published name against the manifest,
so a name and its bytes cannot disagree unnoticed again. A superseded path is exempt: its
name is frozen, and its entry already points at the file that corrects it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUDIO = frozenset({"mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "aiff"})
UNITS = {"b": 1, "kb": 10**3, "mb": 10**6, "gb": 10**9, "kib": 2**10, "mib": 2**20}
#: Bits per pixel for the image modes a name's `24bit` can refer to.
MODE_BITS = {"1": 1, "L": 8, "P": 8, "RGB": 24, "RGBA": 32, "CMYK": 32}
#: The tolerance an approximate size class allows (docs/05 §6).
APPROXIMATE = 0.05
DURATION_TOLERANCE_MS = 150


def claims(entry: dict[str, Any]) -> list[tuple[str, str | None]]:
    """(token, problem) for every claim a path's file name makes; problem is None when the
    measured props bear it out."""
    props = entry.get("props") or {}
    stem = entry["path"].rsplit("/", 1)[1].split(".", 1)[0]
    tokens = stem.split("-")
    found: list[tuple[str, str | None]] = []
    for index, token in enumerate(tokens):
        if match := re.fullmatch(r"(\d+)x(\d+)", token):
            named = tuple(map(int, match.groups()))
            measured = (props.get("width"), props.get("height"))
            found.append((token, None if measured == named else f"measures {measured}"))
        elif match := re.fullmatch(r"(\d+)p", token):
            height = props.get("height")
            found.append((token, None if height == int(match[1]) else f"height {height}"))
        elif match := re.fullmatch(r"(\d+)s", token):
            duration = props.get("duration_ms")
            ok = duration is not None and (
                abs(duration - int(match[1]) * 1000) <= DURATION_TOLERANCE_MS
            )
            found.append((token, None if ok else f"duration {duration} ms"))
        elif match := re.fullmatch(r"(\d+)(b|kb|mb|gb|kib|mib)", token):
            named = int(match[1]) * UNITS[match[2]]
            after = tokens[index + 1 : index + 3]
            named += {("minus", "1"): -1, ("plus", "1"): 1}.get(tuple(after), 0)
            size = entry["bytes"]
            ok = (
                size == named
                if entry["size_class"] == "exact"
                else (abs(size - named) <= APPROXIMATE * named)
            )
            found.append(
                (token, None if ok else f"{size:,} bytes, size class {entry['size_class']}")
            )
        elif match := re.fullmatch(r"(\d+)k", token):
            named = int(match[1])
            if entry["format"] in AUDIO:
                rate, bitrate = props.get("sample_rate"), props.get("bitrate_kbps")
                ok = (rate is not None and abs(rate - named * 1000) < 1000) or (
                    bitrate is not None and round(bitrate) == named
                )
                found.append((token, None if ok else f"sample rate {rate}, bitrate {bitrate}"))
            else:
                rows = props.get("rows")
                found.append((token, None if rows == named * 1000 else f"rows {rows}"))
        elif match := re.fullmatch(r"(\d+)bit", token):
            if entry["format"] in AUDIO:
                depth = props.get("bit_depth")
            else:
                depth = MODE_BITS.get(str(props.get("mode")))
            found.append((token, None if depth == int(match[1]) else f"depth {depth}"))
    return found


def published() -> list[dict[str, Any]]:
    document = json.loads((ROOT / "manifest.json").read_text())
    return [e for e in document["fixtures"] if e.get("status", "active") == "active"]


#: Names that read differently from the props, each for a reason that is not an error, and
#: each with the measurement that bears its own reading out.
PINNED: dict[str, tuple[str, Any]] = {
    "jpg/exif-orientation-6-640x480.jpg": (
        "names the displayed size; the props record the stored, rotated pixels",
        lambda p: p["exif_orientation"] == 6 and (p["height"], p["width"]) == (640, 480),
    ),
    "jpg/exif-orientation-8-640x480.jpg": (
        "names the displayed size; the props record the stored, rotated pixels",
        lambda p: (p["display_width"], p["display_height"]) == (640, 480),
    ),
    **{
        f"{fmt}/lorem-1mb.txt.{fmt}": (
            "a compressed stream named after the 1 MB text it holds",
            lambda p: p["uncompressed_bytes"] == 1_000_000,
        )
        for fmt in ("gz", "bz2", "xz", "zst")
    },
}


def mismatched() -> dict[str, list[str]]:
    return {
        e["path"]: [f"{token}: {problem}" for token, problem in claims(e) if problem]
        for e in published()
        if not e.get("supersededBy") and any(problem for _, problem in claims(e))
    }


def test_every_published_name_agrees_with_its_bytes_or_is_pinned() -> None:
    assert sorted(mismatched()) == sorted(PINNED)


@pytest.mark.parametrize("path", sorted(PINNED))
def test_each_pin_is_borne_out_by_its_own_measurement(path: str) -> None:
    entry = {e["path"]: e for e in published()}[path]
    assert PINNED[path][1](entry["props"]), PINNED[path][0]


def test_the_names_the_guard_reads_are_the_ones_it_should() -> None:
    """Empty-set control: one name per kind of claim, each found and each borne out."""
    entries = {e["path"]: e for e in published()}
    expected = {
        "png/640x480.png": "640x480",
        "mp4/720p-5s.mp4": "720p",
        "mp3/sine-440hz-30s.mp3": "30s",
        "bin/10mb-plus-1.bin": "10mb",
        "wav/sine-440hz-3s-44k-16bit-stereo.wav": "44k",
        "opus/cbr-32k-30s.opus": "32k",
        "csv/people-100k.csv": "100k",
        "bmp/24bit-256x256.bmp": "24bit",
    }
    for path, token in expected.items():
        assert (token, None) in claims(entries[path]), path


def test_the_superseded_cmyk_path_is_the_mismatch_this_guard_exists_for() -> None:
    old = {e["path"]: e for e in published()}["jpg/cmyk-640x480.jpg"]
    assert old["supersededBy"] == "jpg/cmyk-640x640.jpg"
    assert claims(old) == [("640x480", "measures (640, 640)")]
    assert "jpg/cmyk-640x480.jpg" not in mismatched(), "superseded paths are exempt"


@pytest.mark.parametrize(
    ("entry", "token"),
    [
        (
            {"path": "jpg/a-640x480.jpg", "format": "jpg", "props": {"width": 640, "height": 640}},
            "640x480",
        ),
        ({"path": "mp4/720p.mp4", "format": "mp4", "props": {"height": 360}}, "720p"),
        ({"path": "mp3/a-30s.mp3", "format": "mp3", "props": {"duration_ms": 31_000}}, "30s"),
        (
            {"path": "bin/1mb.bin", "format": "bin", "bytes": 1_000_001, "size_class": "exact"},
            "1mb",
        ),
        ({"path": "pdf/1mb.pdf", "format": "pdf", "bytes": 900_000, "size_class": "approx"}, "1mb"),
        ({"path": "wav/a-44k.wav", "format": "wav", "props": {"sample_rate": 48_000}}, "44k"),
        ({"path": "csv/a-100k.csv", "format": "csv", "props": {"rows": 10}}, "100k"),
        ({"path": "wav/a-24bit.wav", "format": "wav", "props": {"bit_depth": 16}}, "24bit"),
    ],
    ids=["size", "height", "duration", "exact bytes", "approximate bytes", "rate", "rows", "depth"],
)
def test_each_kind_of_claim_is_caught_when_wrong(entry: dict[str, Any], token: str) -> None:
    entry = {"bytes": 1, "size_class": "free", "props": {}} | entry
    assert any(found == token and problem for found, problem in claims(entry))
