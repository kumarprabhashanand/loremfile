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
    DESCRIPTION_FLOOR,
    DESCRIPTION_LIMIT,
    LABELS,
    MEASURED_TAIL,
    MEASURED_TAIL_ONE,
    TITLE_LIMIT,
    SiteError,
    human_bytes,
    label,
    labelled_description,
    labelled_title,
    measured_description,
    page_labels,
    title_head,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = Catalog.load()
MANIFEST = {e["path"]: e for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
#: "100,000" is one number, not 100 and 000.
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?")
#: Names whose digits are part of the name, not a quantity: removed before numbers are read.
NAMES = re.compile(r"\b(?:ID3v2|H\.264|VP9|ZIP64|UTF-8|A4|MPEG-4 Part 2|MP3)\b")
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
    avi = MANIFEST["avi/640x480-5s.avi"]["props"]
    assert unmeasured("MPEG-4 Part 2 and MP3", avi) == []
    assert unmeasured("2 MP3 tracks", avi) == ["2"], "the name is skipped, the count is not"
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


#: The twelve of 2026-10-22, written out: a guide is never removed because its format draws
#: no queries (owner, 2026-11-08), so the set may grow and may not lose one of these.
ORIGINAL_TWELVE = frozenset(
    {"mp3", "mp4", "parquet", "docx", "pptx", "mkv", "png", "jpg", "pdf", "csv", "zip", "wav"}
)
#: Added on 2026-11-08 for measured query demand and no guide. tiff was already labelled.
ADDED_2026_11_08 = frozenset({"sqlite", "tiff", "avi", "eml"})


def test_the_labelled_pages_are_the_first_three_and_the_demand_formats() -> None:
    """1.9.0's three (2026-10-16), the twelve formats with search demand (2026-10-22) and
    sqlite, tiff, avi and eml (2026-11-08); the other 62 stay on the plain title. A
    superseded file needs no label."""
    complete = {
        fmt.format for fmt in CATALOG.formats if all(f.label for f in recommended(fmt.format))
    }
    assert complete == LABELLED_FORMATS
    assert DEMAND_FORMATS == ORIGINAL_TWELVE | ADDED_2026_11_08 and len(DEMAND_FORMATS) == 16
    assert ORIGINAL_TWELVE.issubset(DEMAND_FORMATS), "no existing guide is removed"
    # Control: dropping one of the twelve is what that line is here to catch.
    assert not ORIGINAL_TWELVE.issubset(DEMAND_FORMATS - {"wav"})


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
                "Sample SQLite database files for testing",
                f"Sample {label(fmt)} files for testing",
                f"Sample {label(fmt)} file for testing",
            }, title
        else:
            assert title.startswith(f"Sample {label(fmt)} files: "), title
        assert DESCRIPTION_FLOOR <= len(description) <= DESCRIPTION_LIMIT, description
        assert f"{label(fmt)} test file" in description
        span = (
            f"from {human_bytes(min(sizes))} to {human_bytes(max(sizes))}"
            if len(sizes) > 1
            else f"of {human_bytes(sizes[0])}"
        )
        assert description.startswith(
            f"{len(sizes)} {label(fmt)} test file{'s' if len(sizes) > 1 else ''} {span}: "
        ), "the count and the size range come from the manifest"


def test_a_labelled_page_with_one_file_takes_the_singular_tail_and_stays_in_the_band() -> None:
    """avi (2026-11-08) is the first labelled format with one file. "Direct URLs" and "per
    file" misread for one, and after a single label the plural tail leaves the description
    under the floor; the singular tail is the one the unlabelled shape uses."""
    one = labelled_description("AVI", [1_734_596], ["MPEG-4 Part 2 and MP3"])
    assert one.endswith(MEASURED_TAIL_ONE)
    assert not [w for w in PLURAL_MARKERS if w in one], one
    assert DESCRIPTION_FLOOR <= len(one) <= DESCRIPTION_LIMIT, one
    many = labelled_description("SQLite", [270_336, 131_072], ["foreign key and trigger"])
    assert many.endswith(". Direct URLs, SHA-256 per file, CC0."), "two files keep theirs"
    # Control: the plural tail on the same single file fails both checks it is here for.
    plural = "1 AVI test file of 1.7 MB: MPEG-4 Part 2 and MP3. Direct URLs, SHA-256 per file, CC0."
    assert len(plural) < DESCRIPTION_FLOOR
    assert [w for w in PLURAL_MARKERS if w in plural] == ["URLs"]


def rendered_head(fmt: str, files: int = 2) -> str:
    return title_head(fmt).format(name=label(fmt), s="" if files == 1 else "s")


def test_every_demand_head_names_its_format_as_people_type_it() -> None:
    """docs/05 §1 rule 9: the format key is a keyword too. JPEG is jpg's name and label,
    but people type "jpg"; Parquet passes because the match ignores case."""
    for fmt in sorted(DEMAND_FORMATS):
        assert fmt in rendered_head(fmt).lower(), (fmt, rendered_head(fmt))
    assert rendered_head("jpg") == "Sample JPG files for testing"
    assert label("jpg") == "JPEG", "the format's name stays in the prose and the description"
    # sqlite keeps "database", the word its queries carry (2026-11-08); the control is the
    # default demand head, which is what dropped it.
    assert rendered_head("sqlite") == "Sample SQLite database files for testing"
    default = "Sample {name} file{s} for testing".format(name=label("sqlite"), s="s")
    assert "database" not in default


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
    assert title_head("ogg") == "Sample {name} file{s}", "ogg and arrow keep 1.9.0's head"
    assert title_head("arrow") == "Sample {name} file{s}"
    assert title_head("tiff") == "Sample {name} file{s} for testing", "tiff moved on 2026-11-08"


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


# --- the other 65 formats: the measured description, and the labels it names (2026-11-03) ----


def served(fmt: str) -> list[dict[str, Any]]:
    """What a format page recommends: active entries, not superseded, straight from the manifest."""
    return [
        e
        for e in MANIFEST.values()
        if e["format"] == fmt
        and e.get("status", "active") == "active"
        and not e.get("supersededBy")
    ]


UNLABELLED = sorted({f.format for f in CATALOG.formats} - LABELLED_FORMATS)
#: What only the plural sentence says: "a SHA-256 for each", "them", "Direct URLs".
PLURAL_MARKERS = ("each", "them", "files", "URLs")


def head_of(fmt: str, sizes: list[int]) -> str:
    """The count and size range as the manifest has them, written out independently."""
    span = (
        f"from {human_bytes(min(sizes))} to {human_bytes(max(sizes))}"
        if len(sizes) > 1
        else f"of {human_bytes(sizes[0])}"
    )
    return f"{len(sizes)} {label(fmt)} test file{'s' if len(sizes) > 1 else ''} {span}. "


def test_the_unlabelled_formats_are_the_other_sixty_two() -> None:
    """Empty-set control first: the parametrised tests below pass over no formats at all."""
    assert len(UNLABELLED) == 62
    assert {"sql", "js", "webm", "edge", "7z", "webp"} <= set(UNLABELLED)
    assert not set(UNLABELLED) & LABELLED_FORMATS


@pytest.mark.parametrize("fmt", UNLABELLED)
def test_an_unlabelled_description_is_the_manifests_count_and_sizes_in_the_band(fmt: str) -> None:
    sizes = [e["bytes"] for e in served(fmt)]
    assert sizes, fmt
    description = measured_description(label(fmt), sizes)
    assert description.startswith(head_of(fmt, sizes)), "count, name and range are the manifest's"
    assert DESCRIPTION_FLOOR <= len(description) <= DESCRIPTION_LIMIT, description


@pytest.mark.parametrize("fmt", UNLABELLED)
def test_a_one_file_page_never_reads_like_many_and_the_reverse(fmt: str) -> None:
    """Old template: "1 sample SQL file with stable URLs". Number agreement, both ways."""
    sizes = [e["bytes"] for e in served(fmt)]
    description = measured_description(label(fmt), sizes)
    if len(sizes) == 1:
        assert not [w for w in PLURAL_MARKERS if w in description], description
        assert description.endswith(MEASURED_TAIL_ONE)
    else:
        assert description.endswith(MEASURED_TAIL)
        assert "the file's" not in description


def test_control_the_old_template_fails_the_agreement_check() -> None:
    old = "1 sample SQL file with stable URLs you can hotlink. No signup, no keys, CC0."
    assert [w for w in PLURAL_MARKERS if w in old] == ["URLs"]
    new = measured_description("SQL", [429_900])
    assert new.startswith("1 SQL test file of 429.9 KB. ") and not [
        w for w in PLURAL_MARKERS if w in new
    ]


def test_a_format_with_no_file_left_still_gets_a_description_in_the_band() -> None:
    """A takedown of the last file of a format must not stop the build."""
    description = measured_description("WebP", [])
    assert DESCRIPTION_FLOOR <= len(description) <= DESCRIPTION_LIMIT
    # A count would stand alone; the digits that are there sit inside CC0 and SHA-256.
    assert not re.search(r"(?<![\w-])\d", description), "no count to get wrong"
    assert re.search(r"(?<![\w-])\d", "0 WebP test files"), "control: a standalone count is seen"


def test_edge_reads_edge_case_and_says_how_many() -> None:
    sizes = [e["bytes"] for e in served("edge")]
    assert label("edge") == "edge-case"
    assert measured_description(label("edge"), sizes).startswith(
        f"{len(sizes)} edge-case test files "
    )
    assert len(sizes) > 1, "control: the plural form is the one being read"


def contradicting(rows: list[tuple[str, str, str]]) -> list[str]:
    """Labels whose casing differs from the casing the format's own `seo_title` uses."""
    found = []
    for fmt, name, title in rows:
        match = re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", title, re.IGNORECASE)
        if match and match.group(0) != name:
            found.append(f"{fmt}: label {name!r}, title says {match.group(0)!r}")
    return found


def test_no_label_contradicts_the_casing_its_own_seo_title_uses() -> None:
    rows = [(f.format, label(f.format), f.seo_title) for f in CATALOG.formats]
    named = {fmt: (name, title) for fmt, name, title in rows}
    assert "WebP" in named["webp"][1] and named["webp"][0] == "WebP", "empty-set control"
    assert named["pdf"][0] == "PDF" and "PDF" in named["pdf"][1], "the unchanged majority"
    assert contradicting(rows) == []


def test_control_the_upper_cased_key_is_what_the_casing_check_catches() -> None:
    """These five read "7Z", "MBOX", "OPUS", "WEBM" and "WEBP" before 2026-11-03."""
    before = [
        ("7z", "7Z", "Sample 7z archives for testing extractors, free and CC0"),
        ("mbox", "MBOX", "Sample mbox file for testing mail importers, free and CC0"),
        ("opus", "OPUS", "Sample Opus audio files for testing, free, CC0 and hotlinkable"),
        ("webm", "WEBM", "Sample WebM video files for testing, free, CC0 and hotlinkable"),
        ("webp", "WEBP", "Sample WebP images for testing, free and CC0"),
    ]
    assert len(contradicting(before)) == 5
    assert contradicting([("pdf", "PDF", "Sample PDF files for testing")]) == []


def test_every_key_in_labels_is_a_published_format() -> None:
    assert {"edge", "7z", "webp", "jpg", "txt"} <= set(LABELS), "empty-set control"
    assert sorted(set(LABELS) - {f.format for f in CATALOG.formats}) == []
