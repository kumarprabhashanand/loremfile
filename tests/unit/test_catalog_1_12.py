"""Catalogue 1.12.0: the phase-1 document rows that were not in the launch set.

Twenty-five files in six formats. Every file is built twice in fresh directories and must
match itself. Every control builds the file *without* its one declared difference, or builds
the nearest ordinary file instead, and watches the validator refuse it for the property
that difference carries, so a refusal can only be about that. Every structural check the
validators gained is shown to fire on a file broken in exactly that way.
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader, PdfWriter

from loremfile import build as build_module
from loremfile import datasets
from loremfile.build import load_generators
from loremfile.catalog import Catalog
from loremfile.generators import office
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util import zipnorm
from loremfile.util.determinism import deterministic
from loremfile.validators import load, validate

ROOT = Path(__file__).resolve().parents[2]
CATALOG = Catalog.load()
MANIFEST = {e["path"]: e for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
load_generators()
load()

PATHS = (
    "pdf/a4-100pages.pdf",
    "pdf/mixed-sizes-3pages.pdf",
    "pdf/a4-with-links-1page.pdf",
    "pdf/a4-with-outline-5pages.pdf",
    "pdf/a4-rotated-90-1page.pdf",
    "pdf/a4-latin1-accents-1page.pdf",
    "docx/10pages.docx",
    "docx/with-headers-footers.docx",
    "docx/with-headings-and-toc.docx",
    "docx/with-comments.docx",
    "docx/unicode-multilingual.docx",
    "xlsx/1sheet-100k-rows.xlsx",
    "xlsx/3sheets.xlsx",
    "xlsx/unicode-strings.xlsx",
    "xlsx/with-chart.xlsx",
    "xlsx/with-frozen-header-and-autofilter.xlsx",
    "xlsx/with-images.xlsx",
    "xlsx/with-merged-cells.xlsx",
    "pptx/10mb.pptx",
    "pptx/with-images.pptx",
    "pptx/with-notes.pptx",
    "pptx/with-table-and-chart.pptx",
    "rtf/with-table-and-formatting.rtf",
    "epub/epub2-3chapters.epub",
    "epub/with-images.epub",
)
#: Minutes between them, not seconds: built and validated on their own.
LARGE = ("xlsx/1sheet-100k-rows.xlsx", "pptx/10mb.pptx")
SMALL = tuple(path for path in PATHS if path not in LARGE)

_DEPENDENCIES: dict[str, bytes] = {}


def resolve(path: str) -> bytes:
    """A dependency, generated here: the PNG generator reproduces the published bytes."""
    if path not in _DEPENDENCIES:
        work = Path(tempfile.mkdtemp())
        _DEPENDENCIES[path] = build_module.generate_one(CATALOG.by_path[path], work, resolve).data
    return _DEPENDENCIES[path]


def build(path: str, directory: Path, generator: str | None = None, **overrides: Any) -> bytes:
    """The fixture as catalogued, or with `overrides`, or by another generator entirely."""
    directory.mkdir(parents=True, exist_ok=True)
    entry = CATALOG.by_path[path]
    context = GeneratorContext(path=path, workdir=directory)
    context._dependency = resolve
    params = overrides if generator else entry.params | overrides
    with deterministic(context.seed):
        out = REGISTRY.get(generator or entry.generator)(context, **params)
    return out if isinstance(out, bytes) else out.read_bytes()


def failures(path: str, data: bytes) -> list[str]:
    entry = CATALOG.by_path[path]
    return validate(data, entry, CATALOG.mime_for(entry)).failures


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("catalog-1-12")
    return {path: build(path, root / str(index)) for index, path in enumerate(SMALL)}


def test_the_batch_is_twenty_five_files_in_six_formats() -> None:
    """Named, so a catalog edit that drops a row fails here rather than shrinking the suite."""
    assert len(PATHS) == len(set(PATHS)) == 25
    assert all(path in CATALOG.by_path for path in PATHS)
    counts = {fmt: sum(p.startswith(f"{fmt}/") for p in PATHS) for fmt in ("pdf", "docx", "xlsx")}
    assert counts == {"pdf": 6, "docx": 5, "xlsx": 7}
    assert {path.split("/")[0] for path in PATHS} == {"pdf", "docx", "xlsx", "pptx", "rtf", "epub"}
    assert set(LARGE) <= set(PATHS) and len(SMALL) == 23
    assert not {"pptx/with-table.pptx", "pptx/with-chart.pptx"} & set(PATHS), "1.10.0's, not these"


@pytest.mark.container
@pytest.mark.parametrize("path", SMALL)
def test_each_file_validates_and_reproduces_in_a_fresh_directory(path, built, tmp_path):
    entry = CATALOG.by_path[path]
    report = validate(built[path], entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures
    assert built[path] == build(path, tmp_path)
    # The committed manifest is the lock: what is built here is what it published.
    assert hashlib.sha256(built[path]).hexdigest() == MANIFEST[path]["sha256"]
    assert len(built[path]) == MANIFEST[path]["bytes"]
    assert report.props == MANIFEST[path]["props"]


@pytest.mark.slow
@pytest.mark.container
@pytest.mark.parametrize("path", LARGE)
def test_each_large_file_validates_and_reproduces_in_a_fresh_directory(path, tmp_path):
    first = build(path, tmp_path / "a")
    assert first == build(path, tmp_path / "b")
    assert hashlib.sha256(first).hexdigest() == MANIFEST[path]["sha256"]
    if path == "xlsx/1sheet-100k-rows.xlsx":
        return  # reading 1.4 million cells back twice takes longer than building them: CI's
        # `build --new` validates it in the pull request that adds it, and the manifest pins what it
        # measured (`test_path_claims.py` holds its 100,001 rows)
    entry = CATALOG.by_path[path]
    report = validate(first, entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures
    assert report.props == MANIFEST[path]["props"]


# --- every file is refused without its difference -------------------------------------------

#: (path, substitute generator or None, parameters that remove the difference, what is refused).
WITHOUT: tuple[tuple[str, str | None, dict[str, Any], str], ...] = (
    ("pdf/a4-100pages.pdf", None, {"pages": 99}, "expect.pages"),
    ("pdf/mixed-sizes-3pages.pdf", "pdf.basic", {"pages": 3}, "expect.page_sizes"),
    ("pdf/a4-with-links-1page.pdf", "pdf.basic", {"pages": 1}, "expect.internal_links"),
    ("pdf/a4-with-outline-5pages.pdf", "pdf.basic", {"pages": 5}, "expect.outline_entries"),
    ("pdf/a4-rotated-90-1page.pdf", None, {"degrees": 0}, "expect.page_rotations"),
    ("pdf/a4-latin1-accents-1page.pdf", None, {"accents": False}, "expect.latin1_characters"),
    ("docx/10pages.docx", None, {"pages": 9}, "expect.paragraphs"),
    ("docx/with-headers-footers.docx", "office.docx_pages", {"pages": 3}, "expect.headers"),
    ("docx/with-headings-and-toc.docx", None, {"toc": False}, "expect.toc_fields"),
    ("docx/with-comments.docx", None, {"comments": 2}, "expect.comments"),
    ("docx/unicode-multilingual.docx", None, {"scripts": ["greek"]}, "expect.scripts"),
    ("xlsx/1sheet-100k-rows.xlsx", None, {"rows": 1000}, "expect.rows"),
    ("xlsx/3sheets.xlsx", None, {"sheets": 1}, "expect.sheets"),
    (
        "xlsx/with-frozen-header-and-autofilter.xlsx",
        None,
        {"autofilter": False},
        "expect.auto_filter",
    ),
    ("xlsx/with-merged-cells.xlsx", "office.xlsx_people", {"rows": 10}, "expect.merged_ranges"),
    ("xlsx/with-chart.xlsx", "office.xlsx_people", {"rows": 4}, "expect.charts"),
    ("xlsx/with-images.xlsx", None, {"images": ["png/100x100.png"]}, "expect.images"),
    ("xlsx/unicode-strings.xlsx", None, {"scripts": ["greek"]}, "expect.scripts"),
    ("pptx/10mb.pptx", None, {"size": 1_000_000}, "size_class"),
    ("pptx/with-images.pptx", None, {"images": ()}, "expect.images"),
    ("pptx/with-notes.pptx", None, {"notes": False}, "expect.notes"),
    ("pptx/with-table-and-chart.pptx", None, {"chart": False}, "expect.charts"),
    ("pptx/with-table-and-chart.pptx", None, {"table_rows": 0}, "expect.tables"),
    ("rtf/with-table-and-formatting.rtf", None, {"table_rows": 0}, "expect.table_rows"),
    ("epub/epub2-3chapters.epub", "office.epub3", {}, "expect.epub_version"),
    ("epub/with-images.epub", None, {"images": ()}, "expect.images"),
)


def test_the_controls_cover_every_file() -> None:
    """Empty-set control: a path left out of the table above is a file nothing refuses."""
    assert {path for path, *_ in WITHOUT} == set(PATHS)


@pytest.mark.parametrize(
    ("path", "generator", "overrides", "refused_for"),
    WITHOUT,
    ids=[f"{path}-{refused_for}" for path, _, _, refused_for in WITHOUT],
)
def test_each_file_is_refused_without_its_difference(
    path, generator, overrides, refused_for, tmp_path
):
    found = failures(path, build(path, tmp_path, generator, **overrides))
    assert any(refused_for in failure for failure in found), (refused_for, found)


# --- the structural checks each fire on a file broken in exactly that way -------------------


def edit(data: bytes, part: str, old: str, new: str, *, epub: bool = False) -> bytes:
    """`data` with `old` replaced by `new` in one part, rebuilt as the generators rebuild it."""
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        members = {name: source.read(name) for name in source.namelist()}
    assert old.encode() in members[part], f"control: {old!r} is in {part}"
    members[part] = members[part].replace(old.encode(), new.encode(), 1)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for name, payload in members.items():
            target.writestr(name, payload)
    return zipnorm.normalize(out.getvalue(), epub=epub)


def refused_with(path: str, whole: bytes, broken: bytes, message: str) -> None:
    """`broken` is refused for `message`; the control is that `whole`, as built, is not."""
    assert failures(path, whole) == [], "control: it passes as built"
    found = failures(path, broken)
    assert any(message in failure for failure in found), (message, found)


def test_a_toc_entry_that_names_no_heading_is_refused(built) -> None:
    path = "docx/with-headings-and-toc.docx"
    refused_with(
        path,
        built[path],
        edit(built[path], "word/document.xml", "Chapter 1:", "Chapter X:"),
        "do not match the headings",
    )


def test_a_toc_entry_on_the_wrong_page_is_refused(built) -> None:
    path = "docx/with-headings-and-toc.docx"
    stale = edit(built[path], "word/document.xml", "<w:tab/><w:t>2</w:t>", "<w:tab/><w:t>9</w:t>")
    refused_with(path, built[path], stale, "is on page 9, not 2")


def test_a_toc_field_that_is_never_closed_is_refused(built) -> None:
    path = "docx/with-headings-and-toc.docx"
    open_ended = edit(built[path], "word/document.xml", '<w:fldChar w:fldCharType="end"/>', "")
    refused_with(path, built[path], open_ended, "is not closed")


def test_updatefields_after_compat_is_refused(built) -> None:
    path = "docx/with-headings-and-toc.docx"
    settings = built[path]
    out_of_order = edit(settings, "word/settings.xml", '<w:updateFields w:val="true"/>', "")
    out_of_order = edit(
        out_of_order,
        "word/settings.xml",
        "</w:compat>",
        '</w:compat><w:updateFields w:val="true"/>',
    )
    refused_with(path, built[path], out_of_order, "out of order")


def test_a_comment_with_no_end_anchor_is_refused(built) -> None:
    path = "docx/with-comments.docx"
    anchor = '<w:commentRangeEnd w:id="0"/>'
    refused_with(
        path,
        built[path],
        edit(built[path], "word/document.xml", anchor, ""),
        "comment anchors disagree",
    )


def test_a_header_reference_that_points_at_nothing_is_refused(built) -> None:
    path = "docx/with-headers-footers.docx"
    with zipfile.ZipFile(io.BytesIO(built[path])) as package:
        document = package.read("word/document.xml").decode()
    start = document.index("<w:headerReference")
    reference = document[start : document.index("/>", start) + 2]
    rid = reference.split('r:id="')[1].split('"')[0]
    dangling = edit(built[path], "word/document.xml", reference, reference.replace(rid, "rId999"))
    refused_with(path, built[path], dangling, "points at no part")


def test_a_ragged_rtf_row_an_unknown_colour_and_an_undeclared_font_are_each_refused(built) -> None:
    path = "rtf/with-table-and-formatting.rtf"
    text = built[path].decode("ascii")
    cases = {
        "cell edge": text.replace(r"\cell \row", r"\row", 1),
        "colour": text.replace(r"{\cf2 ", r"{\cf9 ", 1),
        "font": text.replace(r"{\f1 ", r"{\f7 ", 1),
        "opened and": text.replace(r"\row", "", 1),
    }
    assert failures(path, built[path]) == [], "control: it passes as built"
    for message, broken in cases.items():
        assert broken != text, f"control: the {message} edit changed the file"
        found = failures(path, broken.encode("ascii"))
        assert any(message in failure for failure in found), (message, found)


def test_an_epub_manifest_item_with_no_file_behind_it_is_refused(built) -> None:
    path = "epub/epub2-3chapters.epub"
    with zipfile.ZipFile(io.BytesIO(built[path])) as package:
        members = {name: package.read(name) for name in package.namelist()}
    members.pop("OEBPS/chapter-2.xhtml")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for name, payload in members.items():
            target.writestr(name, payload)
    refused_with(
        path, built[path], zipnorm.normalize(out.getvalue(), epub=True), "is not in the book"
    )


def test_an_ncx_uid_that_is_not_the_books_identifier_is_refused(built) -> None:
    path = "epub/epub2-3chapters.epub"
    wrong = edit(
        built[path], "OEBPS/toc.ncx", 'content="urn:uuid:', 'content="urn:uuid:0', epub=True
    )
    refused_with(path, built[path], wrong, "is not the book's identifier")


def test_an_epub2_spine_without_its_ncx_is_refused(built) -> None:
    path = "epub/epub2-3chapters.epub"
    refused_with(
        path,
        built[path],
        edit(built[path], "OEBPS/content.opf", '<spine toc="ncx">', "<spine>", epub=True),
        "does not name an NCX",
    )


def test_an_image_with_no_alt_text_and_one_the_manifest_lacks_are_each_refused(built) -> None:
    path = "epub/with-images.epub"
    bare = edit(
        built[path],
        "EPUB/chapter-1.xhtml",
        ' alt="Published fixture png/100x100.png"',
        "",
        epub=True,
    )
    refused_with(path, built[path], bare, "with no alt text")
    missing = edit(
        built[path],
        "EPUB/chapter-1.xhtml",
        'src="images/100x100.png"',
        'src="images/none.png"',
        epub=True,
    )
    refused_with(path, built[path], missing, "not an image in the manifest")


def test_a_chart_that_reads_a_missing_sheet_or_empty_cells_is_refused(built) -> None:
    path = "xlsx/with-chart.xlsx"
    elsewhere = edit(
        built[path], "xl/charts/chart1.xml", "'Signups'!$B$2:$B$5", "'Nowhere'!$B$2:$B$5"
    )
    refused_with(path, built[path], elsewhere, "which the workbook does not have")
    empty = edit(built[path], "xl/charts/chart1.xml", "$B$2:$B$5", "$Z$2:$Z$5")
    refused_with(path, built[path], empty, "which holds nothing")


def test_a_link_to_no_page_and_a_bookmark_to_no_page_are_each_refused(built) -> None:
    links = "pdf/a4-with-links-1page.pdf"
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(built[links])))
    for annotation in writer.pages[0]["/Annots"]:
        node = annotation.get_object()
        if "/Dest" in node:
            node["/Dest"][0] = writer._root_object["/Pages"].indirect_reference
    out = io.BytesIO()
    writer.write(out)
    assert any("lands on no page" in f for f in failures(links, out.getvalue()))

    outline = "pdf/a4-with-outline-5pages.pdf"
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(built[outline])))
    writer.remove_page(4)
    out = io.BytesIO()
    writer.write(out)
    assert any("opens no page" in f for f in failures(outline, out.getvalue()))


# --- what the new props leave alone ----------------------------------------------------------

#: Published before this batch, and built here: their measured props must not move.
BEFORE = (
    "pdf/a4-1page.pdf",
    "pdf/a4-3pages.pdf",
    "pdf/a4-encrypted-1page.pdf",
    "pdf/a4-with-table-1page.pdf",
    "pdf/blank-1page.pdf",
    "pdf/minimal.pdf",
    "pdf/letter-1page.pdf",
    "pdf/a4-landscape-1page.pdf",
    "pdf/form-fields-1page.pdf",
    "pdf/scanned-1page.pdf",
    "docx/1page.docx",
    "docx/with-table.docx",
    "docx/with-tracked-changes.docx",
    "xlsx/1sheet-10rows.xlsx",
    "xlsx/with-formulas.xlsx",
    "xlsx/with-types-and-formats.xlsx",
    "xlsx/3sheets-with-formulas.xlsx",
    "pptx/1slide.pptx",
    "pptx/10slides.pptx",
    "pptx/with-chart.pptx",
    "pptx/with-hidden-slide.pptx",
    "pptx/with-table.pptx",
    "rtf/simple.rtf",
    "epub/epub3-3chapters.epub",
)


@pytest.mark.parametrize("path", BEFORE)
def test_a_published_files_props_are_what_they_were(path, tmp_path) -> None:
    """No key appears and none changes: every new prop is reported only where it applies."""
    entry = CATALOG.by_path[path]
    data = build(path, tmp_path)
    assert data and MANIFEST[path]["sha256"], "control: both sides are there"
    report = validate(data, entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures
    assert report.props == MANIFEST[path]["props"]


def test_the_control_would_notice_a_prop_that_moved(tmp_path) -> None:
    """The comparison above is not vacuously equal: add one key and it differs."""
    path = "docx/1page.docx"
    entry = CATALOG.by_path[path]
    props = validate(build(path, tmp_path), entry, CATALOG.mime_for(entry)).props
    assert props == MANIFEST[path]["props"]
    assert {**props, "page_breaks": 0} != MANIFEST[path]["props"]


# --- the claims in the descriptions, each pinned to the fact that makes it true -------------


def test_each_of_three_sheets_holds_the_next_ten_records(built) -> None:
    people = datasets.rows("people", 30)
    workbook = load_workbook(io.BytesIO(built["xlsx/3sheets.xlsx"]))
    firsts = [sheet["A2"].value for sheet in workbook.worksheets]
    assert firsts == [people[0]["id"], people[10]["id"], people[20]["id"]]
    assert len(set(firsts)) == 3, "three different sheets, not one three times"


def test_the_published_pngs_are_the_pictures_in_the_xlsx_pptx_and_epub(built) -> None:
    sources = {resolve("png/100x100.png"), resolve("png/640x480.png")}
    for path, prefix in (
        ("xlsx/with-images.xlsx", "xl/media/"),
        ("pptx/with-images.pptx", "ppt/media/"),
        ("epub/with-images.epub", "EPUB/images/"),
    ):
        with zipfile.ZipFile(io.BytesIO(built[path])) as package:
            embedded = {package.read(n) for n in package.namelist() if n.startswith(prefix)}
        assert embedded == sources, path


def test_the_epub2_identifier_is_a_uuid_and_the_same_in_the_package_and_the_ncx(built) -> None:
    with zipfile.ZipFile(io.BytesIO(built["epub/epub2-3chapters.epub"])) as package:
        opf = package.read("OEBPS/content.opf").decode()
        ncx = package.read("OEBPS/toc.ncx").decode()
        assert package.read("OEBPS/chapter-1.xhtml").decode().count("XHTML 1.1") == 1
    identifier = opf.split('opf:scheme="UUID">')[1].split("<")[0]
    assert uuid.UUID(identifier.removeprefix("urn:uuid:")).version == 4
    assert f'content="{identifier}"' in ncx


def test_the_mixed_pdf_has_the_three_boxes_it_names(built) -> None:
    reader = PdfReader(io.BytesIO(built["pdf/mixed-sizes-3pages.pdf"]))
    boxes = [
        (round(float(p.mediabox.width), 2), round(float(p.mediabox.height), 2))
        for p in reader.pages
    ]
    assert boxes == [(595.28, 841.89), (612.0, 792.0), (595.28, 419.53)]


def test_the_rotated_page_keeps_its_portrait_box_and_says_ninety(built) -> None:
    page = PdfReader(io.BytesIO(built["pdf/a4-rotated-90-1page.pdf"])).pages[0]
    assert page.get("/Rotate") == 90
    assert float(page.mediabox.width) < float(page.mediabox.height)


def test_a_section_of_the_ten_page_document_is_short_enough_to_stay_on_its_page(built) -> None:
    """The longest section the generator can write: three paragraphs of seven 18-word
    sentences. That is the arithmetic the claim "ten pages at the least" rests on."""
    longest = office.PAGED_PARAGRAPHS * 7 * 18
    assert longest == 378
    props = validate(built["docx/10pages.docx"], CATALOG.by_path["docx/10pages.docx"], "x").props
    assert props["words"] <= 10 * (longest + 2), "a heading is two words"


def test_the_large_workbook_names_its_rows_the_way_the_other_one_does() -> None:
    """The 100k name counts records, and the sheet counts its header row too."""
    entry = CATALOG.by_path["xlsx/1sheet-100k-rows.xlsx"]
    assert entry.params == {"rows": 100000} and entry.expect["rows"] == 100001
    assert CATALOG.by_path["xlsx/1sheet-1000rows.xlsx"].expect["rows"] == 1001
