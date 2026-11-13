"""The phase-1 plan index, `catalog/_plan.yaml`, held against docs/05 and the catalog.

The index is written by hand from §3, so it can be wrong in two ways: it can disagree with
§5's family totals (a row missed or invented), and it can disagree with the catalog (a
built row it does not know, or a name that was never the catalog's). Each check below is a
function over plain data so that every one can be shown to fire on a deliberately broken
copy; a guard that has not been watched failing is not evidence about anything.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from loremfile.catalog import Catalog

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "05-fixture-catalog.md").read_text(encoding="utf-8")
PLAN = yaml.safe_load((ROOT / "catalog" / "_plan.yaml").read_text(encoding="utf-8"))["rows"]
MANIFEST = {e["path"]: e for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
CATALOG = Catalog.load()

#: Rows with phase 1 in their own catalog file that are not among §5's 416: each was added
#: by a catalog release after the plan was written, and the value is that release, which
#: the manifest's `added_in` must agree with. A new row with phase 1 and no place in §3's
#: plan has to be added here by name, which is the point.
OUTSIDE_THE_PLAN = {
    "csv/people-10-quoted-commas.csv": "1.3.0",
    "edge/pdf-zip-polyglot.pdf": "1.4.0",
    "edge/gif-zip-polyglot.gif": "1.4.0",
    "ogg/flac-10s.ogg": "1.9.0",
    "ogg/vorbis-mono-22k-10s.ogg": "1.9.0",
    "ogg/vorbis-cover-art-10s.ogg": "1.9.0",
    "ogg/chained-2-streams-10s.ogg": "1.9.0",
    "tiff/16bit-gray-big-endian-640x480.tiff": "1.9.0",
    "tiff/cmyk-640x480.tiff": "1.9.0",
    "arrow/people-1000-zstd.arrow": "1.9.0",
    "arrow/people-1000.arrows": "1.9.0",
    "arrow/people-1000-10-batches.arrow": "1.9.0",
    "arrow/all-types.arrow": "1.9.0",
    "wav/sine-440hz-3s-44k-16bit-mono.wav": "1.10.0",
    "wav/sine-440hz-3s-44k-8bit-stereo.wav": "1.10.0",
    "wav/sine-440hz-3s-44k-32bit-float-stereo.wav": "1.10.0",
    "wav/with-list-chunk-3s.wav": "1.10.0",
    "mkv/with-chapters-720p-5s.mkv": "1.10.0",
    "parquet/people-1000-zstd.parquet": "1.10.0",
    "parquet/people-1000-10-row-groups.parquet": "1.10.0",
    "pptx/aspect-4-3-5slides.pptx": "1.10.0",
    "pptx/with-table.pptx": "1.10.0",
    "pptx/with-chart.pptx": "1.10.0",
    "pptx/with-hidden-slide.pptx": "1.10.0",
    "mkv/vp9-opus-720p-5s.mkv": "1.11.0",
}

#: Plan rows whose own catalog file says phase 2. The manifest carries `phase`, so a
#: published row's cannot be edited; §3 lists this one under "all P1" and §5 counts it.
PLAN_ROWS_CATALOGUED_AS_PHASE_2 = ("wav/sine-440hz-3s-48k-24bit-stereo.wav",)

#: Families with every plan row catalogued. A family joins when its last row does, so a
#: later release that drops one fails here instead of leaving the remainder to be inferred.
COMPLETE_FAMILIES = ("documents", "images", "video")

#: How §3 writes a name that a literal search for the name does not find. Each value is the
#: text §3 must hold for the name to be there at all.
SHORTHAND = {
    "jpg/exif-orientation-3-640x480.jpg": "`-3-`",
    "jpg/exif-orientation-6-640x480.jpg": "`-6-`",
    "jpg/exif-orientation-8-640x480.jpg": "`-8-`",
    **{f"hls/720p-10s/seg-00{n}.ts": "`seg-000.ts`…`seg-004.ts`" for n in range(5)},
    **{
        f"{fmt}/lorem-1mb.txt.{fmt}": "`lorem-1mb.txt.{bz2,xz,zst}`" for fmt in ("bz2", "xz", "zst")
    },
}


def section(doc: str, start: str, end: str) -> str:
    return doc.split(start, 1)[1].split(end, 1)[0]


def read_totals(doc: str) -> tuple[dict[str, tuple[list[str], int]], int]:
    """§5's family table: family -> (formats, phase-1 files), and the stated grand total."""
    table = section(doc, "## 5. Phase 1 totals", "**Measured, the launch set")
    families = {
        family: ([f.strip() for f in formats.split(",")], int(total))
        for family, formats, total in re.findall(
            r"^\| ([a-z][a-z-]*) \| ([a-z0-9, ]+) \| (\d+) \|", table, re.MULTILINE
        )
    }
    grand = re.search(r"^\| \*\*Total\*\* \| \| \*\*(\d+)\*\* \|", table, re.MULTILINE)
    return families, int(grand.group(1)) if grand else -1


FAMILIES, GRAND_TOTAL = read_totals(DOC)
FORMAT_FAMILY = {fmt: family for family, (formats, _) in FAMILIES.items() for fmt in formats}


def paths_of(rows: list[dict[str, Any]]) -> list[str]:
    return [f"{row['format']}/{row['name']}" for row in rows]


def shape_problems(rows: Any) -> list[str]:
    if not isinstance(rows, list):
        return ["rows is not a list"]
    found = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"format", "name"}:
            found.append(f"row {index} is not exactly {{format, name}}: {row!r}")
        elif not all(isinstance(v, str) and v for v in row.values()) or "/" in row["format"]:
            found.append(f"row {index} has an empty or non-string field, or a '/' in format")
    if found:
        return found
    paths = paths_of(rows)
    return [f"listed twice: {p}" for p in sorted({p for p in paths if paths.count(p) > 1})]


def total_problems(
    paths: list[str], families: dict[str, tuple[list[str], int]], grand: int
) -> list[str]:
    found = [
        f"format not in any §5 family: {p}" for p in paths if p.split("/")[0] not in FORMAT_FAMILY
    ]
    for family, (formats, stated) in families.items():
        count = sum(1 for p in paths if p.split("/")[0] in formats)
        if count != stated:
            found.append(f"{family}: the index has {count}, §5 says {stated}")
    if len(paths) != grand:
        found.append(f"the index has {len(paths)}, §5's total says {grand}")
    if sum(stated for _, stated in families.values()) != grand:
        found.append("§5's family totals do not sum to its own total")
    return found


def catalog_problems(
    paths: list[str],
    rows: dict[str, tuple[int, str]],
    outside: dict[str, str],
    phase_2: tuple[str, ...],
    complete: tuple[str, ...],
) -> list[str]:
    """`rows` is the catalog, path -> (phase, family)."""
    planned = set(paths)
    found = [
        f"catalog phase-1 row in neither the plan nor OUTSIDE_THE_PLAN: {p}"
        for p, (phase, _) in sorted(rows.items())
        if phase == 1 and p not in planned and p not in outside
    ]
    for p in sorted(outside):
        if p in planned:
            found.append(f"OUTSIDE_THE_PLAN names a plan row: {p}")
        elif p not in rows:
            found.append(f"OUTSIDE_THE_PLAN names a row the catalog does not have: {p}")
        elif rows[p][0] != 1:
            found.append(f"OUTSIDE_THE_PLAN names a row that is not phase 1: {p}")
    for p in paths:
        if p in rows and rows[p][0] != 1 and p not in phase_2:
            found.append(f"plan row catalogued as phase {rows[p][0]}: {p}")
        if p in rows and rows[p][1] != FORMAT_FAMILY.get(p.split("/")[0]):
            found.append(f"{p}: the catalog says family {rows[p][1]}, §5 says another")
    for p in phase_2:
        if p not in planned or p not in rows or rows[p][0] != 2:
            found.append(f"PLAN_ROWS_CATALOGUED_AS_PHASE_2 is stale for {p}")
    for p in paths:
        if FORMAT_FAMILY.get(p.split("/")[0]) in complete and p not in rows:
            found.append(f"{FORMAT_FAMILY[p.split('/')[0]]} is complete but {p} is not catalogued")
    return found


def release_problems(outside: dict[str, str], manifest: dict[str, Any]) -> list[str]:
    return [
        f"{p}: declared {release}, the manifest says added in {manifest.get(p, {}).get('added_in')}"
        for p, release in sorted(outside.items())
        if manifest.get(p, {}).get("added_in") != release
    ]


def doc_problems(paths: list[str], section3: str) -> list[str]:
    found = []
    for p in paths:
        _, name = p.split("/", 1)
        wanted = SHORTHAND.get(p)
        if wanted is not None:
            present = wanted in section3
        else:
            present = f"`{name}`" in section3 or f"`{p}`" in section3
        if not present:
            found.append(f"not in docs/05 §3: {p}")
    return found


SECTION3 = section(DOC, "## 3. Catalog by format", "## 4. Tag vocabulary")
CATALOG_ROWS = {fx.path: (fx.phase, str(f.family)) for f in CATALOG.formats for fx in f.fixtures}
PATHS = paths_of(PLAN)


def without(rows: list[dict[str, Any]], path: str) -> list[dict[str, Any]]:
    return [r for r in rows if f"{r['format']}/{r['name']}" != path]


# -- the discovery is part of the assertion ---------------------------------------------


def test_the_parses_find_what_they_are_known_to_hold() -> None:
    """Every check below is true of an empty set, so these name specifics instead."""
    assert set(FAMILIES) == {
        "documents", "images", "video", "audio", "text", "web", "data",
        "archives", "fonts", "binary", "calendar-mail", "certificates", "edge",
    }  # fmt: skip
    assert FAMILIES["documents"][1] == 54
    assert FAMILIES["images"][1] == 48
    assert FAMILIES["video"][0] == ["mp4", "webm", "mkv", "mov", "avi", "ogv", "ts", "hls"]
    assert GRAND_TOTAL == 416
    for named in (
        "jpg/exif-orientation-8-640x480.jpg",
        "hls/720p-10s/seg-004.ts",
        "edge/zero-byte.mp4",
        "html/xhtml-strict.xhtml",
        "tar/3-text-files.tar.zst",
        "gz/multi-member-3.gz",
        "webmanifest/site.webmanifest",
        "wasm/minimal-add.wasm",
    ):
        assert named in PATHS, named
    assert {"png/640x480.png", "mkv/720p-5s.mkv", "mp4/720p-5s.mp4"} <= {
        p for p, (phase, _) in CATALOG_ROWS.items() if phase == 1
    }
    assert "`a4-1page.pdf`" in SECTION3 and "## 4." not in SECTION3
    assert "`people-1000.parquet`" in SECTION3


# -- the index against §5 ---------------------------------------------------------------


def test_the_index_is_well_formed() -> None:
    assert shape_problems(PLAN) == []


def test_every_family_total_of_section_5_is_reproduced_and_they_sum_to_416() -> None:
    assert total_problems(PATHS, FAMILIES, GRAND_TOTAL) == []
    assert len(PATHS) == 416


def test_a_row_missing_from_the_index_is_a_family_total_that_does_not_reproduce() -> None:
    short = paths_of(without(PLAN, "pdf/minimal.pdf"))
    assert total_problems(short, FAMILIES, GRAND_TOTAL) == [
        "documents: the index has 53, §5 says 54",
        "the index has 415, §5's total says 416",
    ]


def test_an_invented_row_is_counted_and_an_unlisted_format_is_named() -> None:
    more = [*PATHS, "mp4/invented.mp4", "heic/invented.heic"]
    found = total_problems(more, FAMILIES, GRAND_TOTAL)
    assert "format not in any §5 family: heic/invented.heic" in found
    assert "video: the index has 33, §5 says 32" in found


def test_a_total_that_the_families_do_not_sum_to_is_refused() -> None:
    off = copy.deepcopy(FAMILIES)
    off["edge"] = (off["edge"][0], 39)
    assert "§5's family totals do not sum to its own total" in total_problems(PATHS, off, 416)


def test_a_malformed_or_repeated_row_is_refused() -> None:
    assert shape_problems([*PLAN, {"format": "pdf"}])[0].startswith("row 416 is not exactly")
    assert shape_problems([*PLAN, {"format": "pdf", "name": ""}])[0].startswith("row 416 has")
    assert shape_problems([*PLAN, {"format": "a/b", "name": "c"}])[0].startswith("row 416 has")
    assert shape_problems([*PLAN, PLAN[0]]) == [f"listed twice: {PATHS[0]}"]
    assert shape_problems({"rows": []}) == ["rows is not a list"]


# -- the index against the catalog ------------------------------------------------------


def test_every_catalog_phase_1_row_is_in_the_plan_or_named_as_outside_it() -> None:
    assert (
        catalog_problems(
            PATHS,
            CATALOG_ROWS,
            OUTSIDE_THE_PLAN,
            PLAN_ROWS_CATALOGUED_AS_PHASE_2,
            COMPLETE_FAMILIES,
        )
        == []
    )
    phase_1 = {p for p, (phase, _) in CATALOG_ROWS.items() if phase == 1}
    assert phase_1 == (phase_1 & set(PATHS)) | set(OUTSIDE_THE_PLAN)


def test_a_phase_1_row_the_plan_does_not_know_fails() -> None:
    short = paths_of(without(PLAN, "pdf/minimal.pdf"))
    found = catalog_problems(
        short, CATALOG_ROWS, OUTSIDE_THE_PLAN, PLAN_ROWS_CATALOGUED_AS_PHASE_2, COMPLETE_FAMILIES
    )
    assert found == [
        "catalog phase-1 row in neither the plan nor OUTSIDE_THE_PLAN: pdf/minimal.pdf"
    ]
    fresh = {**CATALOG_ROWS, "mp4/new-row.mp4": (1, "video")}
    assert any(
        "mp4/new-row.mp4" in line
        for line in catalog_problems(
            PATHS, fresh, OUTSIDE_THE_PLAN, PLAN_ROWS_CATALOGUED_AS_PHASE_2, COMPLETE_FAMILIES
        )
    )


def test_a_row_named_as_outside_the_plan_has_to_be_outside_it_and_catalogued() -> None:
    def run(outside: dict[str, str], rows: dict[str, tuple[int, str]] = CATALOG_ROWS) -> list[str]:
        return catalog_problems(
            PATHS, rows, outside, PLAN_ROWS_CATALOGUED_AS_PHASE_2, COMPLETE_FAMILIES
        )

    assert "OUTSIDE_THE_PLAN names a plan row: pdf/minimal.pdf" in run(
        {**OUTSIDE_THE_PLAN, "pdf/minimal.pdf": "1.1.0"}
    )
    assert "OUTSIDE_THE_PLAN names a row the catalog does not have: pdf/ghost.pdf" in run(
        {**OUTSIDE_THE_PLAN, "pdf/ghost.pdf": "1.3.0"}
    )
    demoted = {**CATALOG_ROWS, "ogg/flac-10s.ogg": (2, "audio")}
    assert "OUTSIDE_THE_PLAN names a row that is not phase 1: ogg/flac-10s.ogg" in run(
        OUTSIDE_THE_PLAN, demoted
    )


def test_a_plan_row_catalogued_as_phase_2_is_named_or_it_fails() -> None:
    row = PLAN_ROWS_CATALOGUED_AS_PHASE_2[0]
    assert CATALOG_ROWS[row][0] == 2, "control: the exception is the catalog's own state"
    unnamed = catalog_problems(PATHS, CATALOG_ROWS, OUTSIDE_THE_PLAN, (), COMPLETE_FAMILIES)
    assert unnamed == [f"plan row catalogued as phase 2: {row}"]
    promoted = {**CATALOG_ROWS, row: (1, "audio")}
    stale = catalog_problems(
        PATHS, promoted, OUTSIDE_THE_PLAN, PLAN_ROWS_CATALOGUED_AS_PHASE_2, COMPLETE_FAMILIES
    )
    assert stale == [f"PLAN_ROWS_CATALOGUED_AS_PHASE_2 is stale for {row}"]


def test_a_catalog_family_that_section_5_does_not_give_the_format_fails() -> None:
    moved = {**CATALOG_ROWS, "mp4/720p-5s.mp4": (1, "audio")}
    found = catalog_problems(
        PATHS, moved, OUTSIDE_THE_PLAN, PLAN_ROWS_CATALOGUED_AS_PHASE_2, COMPLETE_FAMILIES
    )
    assert found == ["mp4/720p-5s.mp4: the catalog says family audio, §5 says another"]


def test_a_complete_family_with_an_uncatalogued_row_fails_and_others_may_have_them() -> None:
    uncatalogued = {p: v for p, v in CATALOG_ROWS.items() if p != "mp4/4k-5s.mp4"}
    found = catalog_problems(
        PATHS, uncatalogued, OUTSIDE_THE_PLAN, PLAN_ROWS_CATALOGUED_AS_PHASE_2, ("video",)
    )
    assert found == ["video is complete but mp4/4k-5s.mp4 is not catalogued"]
    assert (
        catalog_problems(PATHS, uncatalogued, OUTSIDE_THE_PLAN, PLAN_ROWS_CATALOGUED_AS_PHASE_2, ())
        == []
    ), "control: the same hole is allowed in a family that is not complete"
    unbuilt = [p for p in PATHS if p not in CATALOG_ROWS]
    assert unbuilt, "control: other families still have rows to build"


def test_the_release_declared_for_an_outside_row_is_the_manifests() -> None:
    assert release_problems(OUTSIDE_THE_PLAN, MANIFEST) == []
    assert len(OUTSIDE_THE_PLAN) == 25
    wrong = {**OUTSIDE_THE_PLAN, "tiff/cmyk-640x480.tiff": "1.10.0"}
    assert release_problems(wrong, MANIFEST) == [
        "tiff/cmyk-640x480.tiff: declared 1.10.0, the manifest says added in 1.9.0"
    ]


# -- the index against §3's own text ----------------------------------------------------


def test_every_name_in_the_index_is_one_section_3_writes() -> None:
    assert doc_problems(PATHS, SECTION3) == []


def test_a_name_section_3_does_not_hold_fails_including_a_shorthand_it_lost() -> None:
    assert doc_problems(["pdf/a4-1page.pdff"], SECTION3) == ["not in docs/05 §3: pdf/a4-1page.pdff"]
    assert doc_problems(["pdf/a4-1page.pdf"], SECTION3) == []
    shorthand = "jpg/exif-orientation-3-640x480.jpg"
    assert doc_problems([shorthand], SECTION3.replace("`-3-`", "`-9-`")) == [
        f"not in docs/05 §3: {shorthand}"
    ]


@pytest.mark.parametrize("mutation", ["54", "416"])
def test_a_changed_section_5_figure_is_seen_by_the_parse(mutation: str) -> None:
    edited = DOC.replace(f"| {mutation} |", "| 999 |", 1).replace(f"**{mutation}**", "**999**", 1)
    families, grand = read_totals(edited)
    assert (families, grand) != (FAMILIES, GRAND_TOTAL)
    assert total_problems(PATHS, families, grand) != []
