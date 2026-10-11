"""Audio and video descriptions state only what a validator measured (docs/04 §1.3).

A sweep before 1.7.0 found the rule had never been checked: an Opus file described at the
encoder's 96 kbps averages 114, an ADTS stream said 128 kbps where its frames average
130.6, and a Vorbis file named an encoder quality no reader can recover. A sweep fixes
numbers once; this keeps them fixed. Five kinds of number are checked: bitrates, sample
rates, bit depths, durations and H.264 levels. A claim with no measurement behind it fails.

The same numbers are checked in the format pages' prose, where a reader meets them: a
sentence is held to the fixture it names, or to the one its paragraph names, or to the page's
only file. A number no single fixture can be held to is listed in KNOWINGLY_UNCHECKED rather
than passed, so a new one fails until it is tied to a file or added there on purpose. An
explanation that is wrong without a wrong number, like the MP3 page's "rounds up to a whole
frame", is beyond any pattern here.

Knowingly unchecked until they are measured: frequencies in Hz (the 440 Hz the sine
fixtures name), which wait for a Goertzel measurement over the decoded PCM in a piece of
their own; and profile names such as "Baseline", which `profile` records but no pattern
here reads.
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
#: A number as copy writes it: thousands separated by commas, or a plain decimal.
NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
KBPS = re.compile(rf"\b({NUMBER}) kbps")
KHZ = re.compile(rf"\b({NUMBER}) kHz")
BITS = re.compile(r"\b(\d+)-bit\b")
MILLISECONDS = re.compile(rf"\b({NUMBER}) ms\b")
LEVEL = re.compile(r"\blevel (\d+\.\d+)\b")
DURATION = re.compile(
    r"\b(about |roughly |just under )?("
    + NUMBER
    + "|"
    + "|".join(NUMBERS)
    + r") (seconds?|minutes?)\b",
    re.IGNORECASE,
)
#: The validators' own duration tolerance, and a tenth for "about" and "roughly".
TOLERANCE_MS = 150
APPROXIMATE = 0.1


def value(number: str) -> float:
    return float(number.replace(",", ""))


CHECKED = (KBPS, KHZ, BITS, LEVEL, MILLISECONDS, DURATION)


def claims(text: str) -> list[str]:
    """Every number of a checked kind in a piece of text, as written."""
    return [match.group(0) for pattern in CHECKED for match in pattern.finditer(text)]


def problems(description: str, props: dict[str, Any]) -> list[str]:
    """Every checked number in a description that its measured props do not bear out."""
    found: list[str] = []
    for match in KBPS.finditer(description):
        claim, measured = match.group(1), props.get("bitrate_kbps")
        places = len(claim.partition(".")[2])
        if measured is None or round(measured, places) != value(claim):
            found.append(f"{match.group(0)}, measured {measured}")
    for match in KHZ.finditer(description):
        if props.get("sample_rate") != round(value(match.group(1)) * 1000):
            found.append(f"{match.group(0)}, measured {props.get('sample_rate')}")
    for match in BITS.finditer(description):
        if props.get("bit_depth") != int(match.group(1)):
            found.append(f"{match.group(0)}, measured {props.get('bit_depth')}")
    for match in LEVEL.finditer(description):
        if props.get("level") != match.group(1):
            found.append(f"{match.group(0)}, measured {props.get('level')}")
    for match in MILLISECONDS.finditer(description):
        if props.get("duration_ms") != value(match.group(1)):
            found.append(f"{match.group(0)}, measured {props.get('duration_ms')}")
    return found + _duration_problems(description, props)


def _duration_problems(description: str, props: dict[str, Any]) -> list[str]:
    """Durations in words or digits, against `duration_ms` or a playlist's target duration."""
    found: list[str] = []
    for match in DURATION.finditer(description):
        word = match.group(2).lower()
        count = NUMBERS[word] if word in NUMBERS else value(word)
        claimed = count * (60_000 if match.group(3).lower().startswith("minute") else 1000)
        measured = props.get("duration_ms")
        if measured is None and "target_duration_s" in props:
            measured = props["target_duration_s"] * 1000
        allowed = claimed * APPROXIMATE if match.group(1) else TOLERANCE_MS
        under = (match.group(1) or "").lower() == "just under "
        if measured is None or abs(measured - claimed) > allowed or (under and measured >= claimed):
            found.append(f"{match.group(0)}, measured {measured} ms")
    return found


def media_entries() -> list[dict[str, Any]]:
    document = json.loads((ROOT / "manifest.json").read_text())
    return [
        e
        for e in document["fixtures"]
        if e["format"] in MEDIA and e.get("status", "active") == "active"
    ]


# --- page prose ---------------------------------------------------------------------------

PAGES = ROOT / "site" / "content" / "formats"
GUIDES = ROOT / "site" / "content" / "testing"
ENTRY_PATHS = {e["path"] for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
FILE_MARKER = re.compile(r"^<!-- file: \S+ -->$", re.MULTILINE)
CODE_PATH = re.compile(r"`([a-z0-9]+/[a-z0-9._/-]+\.[a-z0-9]+)`")
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z`])")


def paragraphs(text: str) -> list[tuple[str | None, list[str]]]:
    """Prose as (marked file, sentences) per paragraph. A `<!-- file: PATH -->` line renders
    from the manifest, so it is not prose; it marks the paragraph after it as about PATH."""
    found: list[tuple[str | None, list[str]]] = []
    marked: str | None = None
    for block in re.split(r"\n\s*\n", text):
        if marker := FILE_MARKER.fullmatch(block.strip()):
            marked = marker.group(0).split()[2]
            continue
        sentences = [s for s in SENTENCE_BREAK.split(" ".join(block.split())) if s]
        if sentences:
            found.append((marked, sentences))
        marked = None
    return found


def attribute(
    sentence: str, paragraph: list[str], own: set[str], marked: str | None = None
) -> str | None:
    """The one fixture a sentence's numbers are about, or None when that is not certain.

    The sentence's own path first; then the file a marker line put just above its
    paragraph; then the one path of this format its paragraph names ("The clip is ..."
    after naming the clip); then the page's only file. A sentence that names two fixtures
    is never guessed at.
    """
    named = set(CODE_PATH.findall(sentence)) & ENTRY_PATHS
    if named:
        return named.pop() if len(named) == 1 else None
    if marked is not None:
        return marked
    nearby = {p for s in paragraph for p in CODE_PATH.findall(s)} & own
    if nearby:
        return nearby.pop() if len(nearby) == 1 else None
    return next(iter(own)) if len(own) == 1 else None


def prose_claims(
    pages: dict[str, str],
) -> tuple[list[tuple[str, str, list[str]]], list[tuple[str, str]]]:
    """(page, fixture, problems) for every attributed sentence holding a checked number,
    and (page, claim) for every checked number no single fixture can be held to.

    An unattributed claim is not passed: it is returned, and the test pins the list of
    claims knowingly left unchecked to exactly what the pages say.
    """
    entries = {e["path"]: e for e in media_entries()}
    checked: list[tuple[str, str, list[str]]] = []
    unchecked: list[tuple[str, str]] = []
    everything = {e["path"]: e for e in all_entries()}
    for name, text in sorted(pages.items()):
        own = {path for path in entries if path.startswith(f"{name}/")}
        for marked, paragraph in paragraphs(text):
            for sentence in paragraph:
                found = claims(sentence)
                if not found:
                    continue
                path = attribute(sentence, paragraph, own, marked)
                if path is None:
                    unchecked += [(name, claim) for claim in found]
                else:
                    props = everything[path].get("props") or {}
                    checked.append((name, path, problems(sentence, props)))
    return checked, unchecked


def media_pages() -> dict[str, str]:
    """Every media format page, and every testing guide, which names files of any format."""
    found = {
        page.stem: page.read_text(encoding="utf-8")
        for page in sorted(PAGES.glob("*.md"))
        if page.stem in MEDIA
    }
    found.update(
        {
            f"testing/{page.stem}": page.read_text(encoding="utf-8")
            for page in sorted(GUIDES.glob("*.md"))
        }
    )
    return found


def all_entries() -> list[dict[str, Any]]:
    document = json.loads((ROOT / "manifest.json").read_text())
    return [e for e in document["fixtures"] if e.get("status", "active") == "active"]


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
    assert LEVEL.search(entries["mp4/h264-baseline-720p-5s.mp4"])


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
        ("Baseline profile at level 3.0.", {"level": "3.1"}),
        ("Baseline profile at level 3.0.", {}),
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
        "wrong level",
        "unmeasured level",
    ],
)
def test_each_kind_of_wrong_or_unmeasured_number_is_reported(
    description: str, props: dict[str, Any]
) -> None:
    assert problems(description, props), "a check that cannot fire proves nothing"


#: Numbers about a format rather than a file: what Opus decoders output, and a rate code
#: might wrongly assume. True, and not a fixture's to measure.
KNOWINGLY_UNCHECKED = [("opus", "44.1 kHz"), ("opus", "48 kHz"), ("opus", "48 kHz")]


def test_every_number_page_prose_ties_to_a_fixture_was_measured() -> None:
    checked, _ = prose_claims(media_pages())
    assert [(page, path, found) for page, path, found in checked if found] == []


def test_only_the_known_format_level_numbers_go_unchecked() -> None:
    _, unchecked = prose_claims(media_pages())
    assert sorted(unchecked) == sorted(KNOWINGLY_UNCHECKED)


def test_the_prose_check_ties_the_sentences_it_is_meant_to() -> None:
    """Empty-set control, one per way of tying a sentence to a fixture."""
    checked, _ = prose_claims(media_pages())
    tied = {(page, path) for page, path, _ in checked}
    assert {
        ("aac", "aac/adts-30s.aac"),  # named in the sentence
        ("mp3", "mp3/sine-440hz-3s.mp3"),
        ("opus", "opus/30s.opus"),
        ("wav", "wav/10mb.wav"),  # named earlier in the paragraph
        ("avi", "avi/640x480-5s.avi"),  # the page's only file
        ("testing/media-playback", "mp4/50mb.mp4"),  # the marker line above its paragraph
    } <= tied


def test_the_sentence_the_aac_page_shipped_with_is_caught() -> None:
    shipped = "The file is a 440 Hz sine wave, thirty seconds long, 48 kHz stereo at 128 kbps.\n"
    checked, unchecked = prose_claims({"aac": shipped})
    assert [found for _, _, found in checked] == [["128 kbps, measured 130.6"]]
    assert unchecked == []


def test_a_sentence_naming_two_fixtures_is_reported_not_guessed() -> None:
    both = "`mp3/1mb.mp3` and `mp3/10mb.mp3` use a constant 128 kbps.\n"
    assert prose_claims({"mp3": both}) == ([], [("mp3", "128 kbps")])


def test_a_number_no_fixture_can_be_held_to_is_reported() -> None:
    assert prose_claims({"opus": "Opus decoders produce 48 kHz output.\n"}) == (
        [],
        [("opus", "48 kHz")],
    )


def test_just_under_is_an_upper_bound() -> None:
    assert problems("just under 57 seconds", {"duration_ms": 56_689}) == []
    assert problems("just under 57 seconds", {"duration_ms": 57_100})
    assert problems("just under 57 seconds", {"duration_ms": 40_000})
