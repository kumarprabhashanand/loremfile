"""Labels are authored, and a number in one must be measured (docs/05 §1 rule 9).

A label names what sets a file apart on its page, for the page title and description. It is
written by a person, so it can say "16-bit big-endian" only because a validator measured
16 bits per sample; "fast LZW" or "3x smaller" would be claims nothing checks.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from loremfile.catalog import Catalog
from loremfile.site.build import (
    DESCRIPTION_LIMIT,
    TITLE_LIMIT,
    human_bytes,
    label,
    labelled_description,
    labelled_title,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = Catalog.load()
MANIFEST = {e["path"]: e for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def measured_numbers(value: Any) -> set[float]:
    """Every number in a props value, and its thousandth (kHz from Hz, seconds from ms)."""
    if isinstance(value, bool):
        return set()
    if isinstance(value, int | float):
        return {float(value), round(value / 1000, 6)}
    if isinstance(value, dict):
        return set().union(*(measured_numbers(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(measured_numbers(v) for v in value)) if value else set()
    return set()


def unmeasured(text: str, props: dict[str, Any]) -> list[str]:
    known = measured_numbers(props)
    return [n for n in NUMBER.findall(text) if float(n) not in known]


LABELLED = [f for f in CATALOG.fixtures() if f.label]


def test_some_fixtures_are_labelled() -> None:
    """The empty-set control: the rule below holds of nothing if no label exists."""
    assert {f.path for f in LABELLED} >= {
        "tiff/16bit-gray-big-endian-640x480.tiff",
        "ogg/vorbis-mono-22k-10s.ogg",
        "arrow/people-1000-10-batches.arrow",
    }


def test_every_number_in_a_label_is_a_measured_one() -> None:
    for fixture in LABELLED:
        props = MANIFEST[fixture.path].get("props") or {}
        assert unmeasured(fixture.label or "", props) == [], (fixture.path, fixture.label)


def test_control_an_invented_number_is_caught() -> None:
    props = MANIFEST["tiff/lzw-640x480.tiff"]["props"]
    assert unmeasured("3x faster LZW", props) == ["3"]
    assert (
        unmeasured(
            "16-bit big-endian", MANIFEST["tiff/16bit-gray-big-endian-640x480.tiff"]["props"]
        )
        == []
    )


def test_only_the_first_three_pages_are_labelled_until_they_are_read() -> None:
    """Reviewer, 2026-10-16: hold the other formats until these show whether titles move."""
    complete = {
        fmt.format
        for fmt in CATALOG.formats
        if fmt.fixtures and all(f.label for f in fmt.fixtures if f.status.value == "active")
    }
    assert complete == {"ogg", "tiff", "arrow"}


def test_the_labelled_titles_and_descriptions_fit_and_say_test() -> None:
    for fmt in ("ogg", "tiff", "arrow"):
        info = CATALOG.format_by_name[fmt]
        labels = [f.label or "" for f in info.fixtures]
        title = labelled_title(label(fmt), labels)
        description = labelled_description(
            label(fmt), [MANIFEST[f.path]["bytes"] for f in info.fixtures], labels
        )
        assert len(title) <= TITLE_LIMIT, title
        assert title.startswith(f"Sample {label(fmt)} files: ")
        assert "loremfile.dev" not in title
        assert len(description) <= DESCRIPTION_LIMIT, description
        assert f"{label(fmt)} test files" in description
        sizes = [MANIFEST[f.path]["bytes"] for f in info.fixtures]
        assert description.startswith(
            f"{len(sizes)} {label(fmt)} test files from {human_bytes(min(sizes))} "
            f"to {human_bytes(max(sizes))}: "
        ), "the count and the size range come from the manifest"


def test_a_label_that_does_not_fit_ends_the_title_rather_than_being_cut() -> None:
    title = labelled_title("TIFF", ["uncompressed RGB", "LZW", "3 pages", "16-bit big-endian"])
    assert title == "Sample TIFF files: uncompressed RGB, LZW, 3 pages"
