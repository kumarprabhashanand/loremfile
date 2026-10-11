"""Audio and video descriptions state only what a validator measured (docs/04 §1.3).

A sweep before 1.7.0 found the rule had never been checked: an Opus file described at the
encoder's 96 kbps averages 114, an ADTS stream said 128 kbps where its frames average
130.6, and a Vorbis file named an encoder quality no reader can recover. A sweep fixes
numbers once; this keeps them fixed. Four kinds of number are checked: bitrates, sample
rates, bit depths and durations. A claim with no measurement behind it fails too.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
MEDIA = frozenset(
    {"mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "aiff"}
    | {"mp4", "webm", "mkv", "mov", "avi", "ogv", "ts", "hls"}
)
NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
}  # fmt: skip
KBPS = re.compile(r"(\d+(?:\.\d+)?) kbps")
KHZ = re.compile(r"(\d+(?:\.\d+)?) kHz")
BITS = re.compile(r"\b(\d+)-bit\b")
MILLISECONDS = re.compile(r"\b(\d+) ms\b")
DURATION = re.compile(
    r"\b(about |roughly )?(\d+|" + "|".join(NUMBERS) + r") (seconds?|minutes?)\b", re.IGNORECASE
)
#: The validators' own duration tolerance, and a tenth for "about" and "roughly".
TOLERANCE_MS = 150
APPROXIMATE = 0.1


def problems(description: str, props: dict[str, Any]) -> list[str]:
    """Every checked number in a description that its measured props do not bear out."""
    found: list[str] = []
    for match in KBPS.finditer(description):
        claim, measured = match.group(1), props.get("bitrate_kbps")
        places = len(claim.partition(".")[2])
        if measured is None or round(measured, places) != float(claim):
            found.append(f"{match.group(0)}, measured {measured}")
    for match in KHZ.finditer(description):
        if props.get("sample_rate") != round(float(match.group(1)) * 1000):
            found.append(f"{match.group(0)}, measured {props.get('sample_rate')}")
    for match in BITS.finditer(description):
        if props.get("bit_depth") != int(match.group(1)):
            found.append(f"{match.group(0)}, measured {props.get('bit_depth')}")
    for match in MILLISECONDS.finditer(description):
        if props.get("duration_ms") != int(match.group(1)):
            found.append(f"{match.group(0)}, measured {props.get('duration_ms')}")
    for match in DURATION.finditer(description):
        word = match.group(2).lower()
        count = int(word) if word.isdigit() else NUMBERS[word]
        claimed = count * (60_000 if match.group(3).lower().startswith("minute") else 1000)
        measured = props.get("duration_ms")
        if measured is None and "target_duration_s" in props:
            measured = props["target_duration_s"] * 1000
        allowed = claimed * APPROXIMATE if match.group(1) else TOLERANCE_MS
        if measured is None or abs(measured - claimed) > allowed:
            found.append(f"{match.group(0)}, measured {measured} ms")
    return found


def media_entries() -> list[dict[str, Any]]:
    document = json.loads((ROOT / "manifest.json").read_text())
    return [
        e
        for e in document["fixtures"]
        if e["format"] in MEDIA and e.get("status", "active") == "active"
    ]


@pytest.mark.parametrize("entry", media_entries(), ids=lambda e: e["path"])
def test_every_number_a_media_description_states_was_measured(entry: dict[str, Any]) -> None:
    assert problems(entry["description"], entry.get("props") or {}) == []


def test_the_check_finds_the_claims_it_is_meant_to_check() -> None:
    """Empty-set control: named claims the patterns must find, so a regex that matched
    nothing could not pass the test above while checking nothing."""
    entries = {e["path"]: e["description"] for e in media_entries()}
    assert KBPS.search(entries["opus/30s.opus"])
    assert KHZ.search(entries["wav/10mb.wav"]) and BITS.search(entries["wav/10mb.wav"])
    assert MILLISECONDS.search(entries["mp3/sine-440hz-3s.mp3"])
    assert DURATION.search(entries["mp3/10mb.mp3"]).group(1) == "roughly "  # type: ignore[union-attr]
    assert DURATION.search(entries["hls/720p-10s/index.m3u8"])


@pytest.mark.parametrize(
    ("description", "props"),
    [
        ("Opus at 96 kbps.", {"bitrate_kbps": 114.0}),
        ("AAC at 128 kbps.", {}),
        ("AAC at 130.6 kbps.", {"bitrate_kbps": 130.4}),
        ("Sampled at 44.1 kHz.", {"sample_rate": 48000}),
        ("A 24-bit file.", {"bit_depth": 16}),
        ("A 24-bit file.", {}),
        ("Measured duration is 3024 ms.", {"duration_ms": 3000}),
        ("Five seconds of tone.", {"duration_ms": 5400}),
        ("Roughly ten minutes.", {"duration_ms": 670_000}),
        ("Five seconds of tone.", {}),
    ],
    ids=[
        "wrong bitrate",
        "unmeasured bitrate",
        "wrong decimal",
        "wrong sample rate",
        "wrong bit depth",
        "unmeasured bit depth",
        "wrong milliseconds",
        "duration past the tolerance",
        "approximate duration past a tenth",
        "unmeasured duration",
    ],
)
def test_each_kind_of_wrong_or_unmeasured_number_is_reported(
    description: str, props: dict[str, Any]
) -> None:
    assert problems(description, props), "a check that cannot fire proves nothing"
