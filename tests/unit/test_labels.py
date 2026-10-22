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

import pytest

from loremfile.catalog import Catalog, Fixture, SizeClass
from loremfile.site.build import (
    DEMAND_FORMATS,
    DESCRIPTION_LIMIT,
    TITLE_LIMIT,
    SiteError,
    human_bytes,
    label,
    labelled_description,
    labelled_title,
    page_labels,
    title_head,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = Catalog.load()
MANIFEST = {e["path"]: e for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
#: "100,000" is one number, not 100 and 000.
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?")
#: Names whose digits are part of the name, not a quantity: removed before numbers are read.
NAMES = re.compile(r"\b(?:ID3v2|H\.264|ZIP64|UTF-8|A4)\b")
#: A size in a label is the catalog's nominal size, which the size-class validator holds the
#: published bytes to (exactly, or within 5%); a free-size file has no size to name.
SIZE = re.compile(r"(\d+(?:\.\d+)?) (KB|MB|GB)\b")
#: An aspect ratio ("4:3") is measured when the props hold both dimensions in that ratio.
RATIO = re.compile(r"\b(\d+):(\d+)\b")
DIMENSIONS = (("slide_width_emu", "slide_height_emu"), ("width", "height"))
UNITS = {"KB": 10**3, "MB": 10**6, "GB": 10**9}


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


def unmeasured(text: str, props: dict[str, Any], fixture: Fixture | None = None) -> list[str]:
    """Numbers in a label that nothing measured: not in the props, and not the size the
    size-class validator checks the published bytes against."""
    problems = []
    for match in SIZE.finditer(text):
        nominal = float(match.group(1)) * UNITS[match.group(2)]
        validated = fixture is not None and fixture.size_class in {
            SizeClass.APPROX,
            SizeClass.EXACT,
        }
        if not validated or fixture is None or nominal != fixture.nominal_bytes:
            problems.append(match.group(0))
        if "exactly" in text and (fixture is None or fixture.size_class is not SizeClass.EXACT):
            problems.append("exactly")
    for match in RATIO.finditer(text):
        across, down = (int(n) for n in match.groups())
        if not any(
            w in props and h in props and props[w] * down == props[h] * across
            for w, h in DIMENSIONS
        ):
            problems.append(match.group(0))
    rest = NAMES.sub(" ", RATIO.sub(" ", SIZE.sub(" ", text)))
    known = measured_numbers(props)
    return problems + [n for n in NUMBER.findall(rest) if float(n.replace(",", "")) not in known]


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
        assert unmeasured(fixture.label or "", props, fixture) == [], (fixture.path, fixture.label)


def test_control_a_wrong_size_a_free_size_and_a_false_exactly_are_caught() -> None:
    sized = CATALOG.by_path["mp3/1mb.mp3"]
    props = MANIFEST[sized.path]["props"]
    assert unmeasured("1 MB", props, sized) == []
    assert unmeasured("2 MB", props, sized) == ["2 MB"]
    assert unmeasured("exactly 1 MB", props, sized) == ["exactly"], "approx is not exact"
    exact = CATALOG.by_path["wav/10mb.wav"]
    assert unmeasured("exactly 10 MB", MANIFEST[exact.path]["props"], exact) == []
    free = CATALOG.by_path["mp3/sine-440hz-3s.mp3"]
    assert unmeasured("1 MB", MANIFEST[free.path]["props"], free) == ["1 MB"]


def test_control_digits_in_a_name_are_not_counted_but_a_count_beside_one_is() -> None:
    props = MANIFEST["mp3/with-id3v2-tags-3s.mp3"]["props"]
    assert unmeasured("ID3v2 tags", props) == []
    assert unmeasured("3 ID3v2 frames", props) == ["3"]
    rows = MANIFEST["csv/people-100k.csv"]["props"]
    assert unmeasured("100,000 rows", rows) == []
    assert unmeasured("100,002 rows", rows) == ["100,002"], "100,001 is measured: lines"


def test_control_a_ratio_must_be_the_measured_one() -> None:
    four_three = {"slide_width_emu": 9144000, "slide_height_emu": 6858000}
    assert unmeasured("4:3 slides", four_three) == []
    assert unmeasured("16:9 slides", four_three) == ["16:9"]
    assert unmeasured("4:3 slides", {"slides": 5}) == ["4:3"], "no dimensions, no ratio"


def test_control_an_invented_number_is_caught() -> None:
    props = MANIFEST["tiff/lzw-640x480.tiff"]["props"]
    assert unmeasured("3x faster LZW", props) == ["3"]
    assert (
        unmeasured(
            "16-bit big-endian", MANIFEST["tiff/16bit-gray-big-endian-640x480.tiff"]["props"]
        )
        == []
    )


LABELLED_FORMATS = {"ogg", "tiff", "arrow"} | DEMAND_FORMATS


def recommended(fmt: str) -> list[Fixture]:
    """The files a page recommends: published, active, not superseded."""
    return [
        f
        for f in CATALOG.format_by_name[fmt].fixtures
        if f.path in MANIFEST
        and MANIFEST[f.path].get("status", "active") == "active"
        and not MANIFEST[f.path].get("supersededBy")
    ]


def test_the_labelled_pages_are_the_first_three_and_the_twelve_demand_formats() -> None:
    """1.9.0's three (2026-10-16) and the twelve formats with search demand (2026-10-22);
    the other 65 stay on the plain title. A superseded file needs no label."""
    complete = {
        fmt.format for fmt in CATALOG.formats if all(f.label for f in recommended(fmt.format))
    }
    assert complete == LABELLED_FORMATS
    assert len(DEMAND_FORMATS) == 12 and {"mp3", "pptx", "mkv", "parquet"} <= DEMAND_FORMATS


def test_the_labelled_titles_and_descriptions_fit_and_say_test() -> None:
    for fmt in sorted(LABELLED_FORMATS):
        info = CATALOG.format_by_name[fmt]
        served = [MANIFEST[f.path] for f in info.fixtures if f.path in MANIFEST]
        labels = page_labels(info, served)
        sizes = [MANIFEST[f.path]["bytes"] for f in recommended(fmt)]
        assert len(labels) == len(sizes), fmt
        title = labelled_title(label(fmt), labels, title_head(fmt))
        description = labelled_description(label(fmt), sizes, labels)
        assert len(title) <= TITLE_LIMIT, title
        assert "loremfile.dev" not in title
        assert not {"free", "CC0", "hotlink"} & set(re.findall(r"[\w-]+", title)), title
        if fmt in DEMAND_FORMATS:
            assert title.startswith("Sample ") and "test" in title, "both words people type"
            assert title.split(":")[0] in {
                "Sample MP3 test files",
                "Sample JPG files for testing",
                f"Sample {label(fmt)} files for testing",
                f"Sample {label(fmt)} file for testing",
            }, title
        else:
            assert title.startswith(f"Sample {label(fmt)} files: "), title
        assert len(description) <= DESCRIPTION_LIMIT, description
        assert f"{label(fmt)} test file" in description
        span = (
            f"from {human_bytes(min(sizes))} to {human_bytes(max(sizes))}"
            if len(sizes) > 1
            else f"of {human_bytes(sizes[0])}"
        )
        assert description.startswith(
            f"{len(sizes)} {label(fmt)} test file{'s' if len(sizes) > 1 else ''} {span}: "
        ), "the count and the size range come from the manifest"


def rendered_head(fmt: str, files: int = 2) -> str:
    return title_head(fmt).format(name=label(fmt), s="" if files == 1 else "s")


def test_every_demand_head_names_its_format_as_people_type_it() -> None:
    """docs/05 §1 rule 9: the format key is a keyword too. JPEG is jpg's name and label,
    but people type "jpg"; Parquet passes because the match ignores case."""
    for fmt in sorted(DEMAND_FORMATS):
        assert fmt in rendered_head(fmt).lower(), (fmt, rendered_head(fmt))
    assert rendered_head("jpg") == "Sample JPG files for testing"
    assert label("jpg") == "JPEG", "the format's name stays in the prose and the description"


def test_control_the_default_head_would_lose_jpg() -> None:
    """Without its query head, jpg's title would say JPEG and never jpg."""
    default = "Sample {name} files for testing".format(name=label("jpg"))
    assert "jpg" not in default.lower()


def test_a_label_that_would_cut_a_keyword_stops_the_build() -> None:
    """docs/05 §1 rule 9: shorten a label before dropping a keyword. The head is never cut;
    a first label too long to follow it is an error naming the head. The control is the
    longest first label that fits, which is kept whole."""
    head = title_head("pdf")
    wide = "Sample PDF file for testing: "  # one label, so "file"
    fits = "x" * (TITLE_LIMIT - len(wide))
    assert labelled_title("PDF", [fits], head) == wide + fits
    with pytest.raises(SiteError, match="shorten the first label"):
        labelled_title("PDF", [fits + "x"], head)
    assert title_head("mp3") == "Sample {name} test file{s}"
    assert title_head("ogg") == "Sample {name} file{s}", "1.9.0's three keep their head"


def test_a_superseded_file_never_contributes_a_label() -> None:
    """jpg/cmyk-640x480.jpg is superseded by jpg/cmyk-640x640.jpg. Given a label anyway, it
    stays out of the list; the control un-supersedes it and the label appears."""
    info = CATALOG.format_by_name["jpg"]
    old = "jpg/cmyk-640x480.jpg"
    assert MANIFEST[old].get("supersededBy") == "jpg/cmyk-640x640.jpg"
    labelled = info.model_copy(
        update={
            "fixtures": [
                f.model_copy(update={"label": "old CMYK"}) if f.path == old else f
                for f in info.fixtures
            ]
        }
    )
    served = [MANIFEST[f.path] for f in info.fixtures]
    assert "old CMYK" not in page_labels(labelled, served)
    assert len(page_labels(labelled, served)) == len(recommended("jpg")) == 10
    unsuperseded = [
        {k: v for k, v in e.items() if k not in ("supersededBy", "deprecated")} for e in served
    ]
    assert "old CMYK" in page_labels(labelled, unsuperseded), "control"
    assert page_labels(info, unsuperseded) == [], "unlabelled and recommended: no labelled title"


def test_a_label_that_does_not_fit_ends_the_title_rather_than_being_cut() -> None:
    title = labelled_title("TIFF", ["uncompressed RGB", "LZW", "3 pages", "16-bit big-endian"])
    assert title == "Sample TIFF files: uncompressed RGB, LZW, 3 pages"
