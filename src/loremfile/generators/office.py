"""Office and e-book fixtures: docx, xlsx, pptx, rtf, epub (docs/05 §3.5).

Four things had to be settled by spike before any of this could be catalogued, because
a nondeterministic fixture that reaches the manifest is frozen there permanently.

1. **openpyxl is not reproducible on its own.** It spools each worksheet to a temporary
   file and adds it with ``ZipFile.write`` (``openpyxl/writer/excel.py``), so that entry
   takes its timestamp from the filesystem — which no clock patch can reach. Raw output
   changed on six of eight consecutive runs; every entry *except* the worksheet sat at
   the patched epoch. ``zipnorm.normalize`` restamps everything and is what actually
   makes xlsx stable, so it is not optional here. python-docx and python-pptx build
   their archives in memory and were byte-identical without it; they are normalised too,
   for entry order and permissions.

2. **These libraries must be imported at module scope, never inside the guard.** They do
   ``from datetime import datetime`` at import time. Imported inside ``deterministic()``
   they bind the guard's stand-in class permanently, and then reject real datetimes once
   the guard exits — openpyxl raised ``TypeError: expected _FixedDatetime`` in the
   validator, in the same process, long after the generator had finished.

3. **Core properties are set explicitly**, as ``pdf.py`` does for fpdf2: relying on the
   patched clock is not enough when a library formats or type-checks the value itself.
   The epoch is built at call time by :func:`_epoch`, never stored as a constant — see
   that function for why.

4. **Cached formula values** are injected into the sheet XML afterwards. openpyxl has no
   API for them and already writes an empty ``<v/>`` placeholder, so the value has to
   replace that element; appending a second ``<v>`` leaves readers taking the empty one.
"""

from __future__ import annotations

import datetime as dt
import io
import random
import re
import zipfile
from typing import Any

import docx
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
from docx.text.paragraph import Paragraph
from lxml import etree
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.image import Image as SheetImage
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.worksheet import Worksheet
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.presentation import Presentation as PresentationDocument
from pptx.util import Inches as PptxInches
from pptx.util import Pt

from loremfile.config import APPROX_TOLERANCE
from loremfile.generators.base import GeneratorContext, generator
from loremfile.util import lorem, zipnorm
from loremfile.util.sizing import fit

#: Everything these documents claim about their own authorship.
AUTHOR = "loremfile.dev"
TITLE = "loremfile.dev sample document"

#: The spreadsheet namespace, for the cached-value injection.
SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

#: Side of the seeded-noise PNG plates the sized fixtures embed (docs/05 §6).
PLATE_SIDE = 256

#: Measured size of one PLATE_SIDE plate plus its paragraph, used to pick the first `n`.
APPROX_PLATE_BYTES = 196_000

#: The threshold the IF formula tests, published in the fixture as a literal.
LARGE_ORDER = 10

#: Alt text for the anchored picture: what a screen reader announces in its place.
ANCHORED_ALT_TEXT = "The loremfile colour-bar test card"

#: A floating picture: aligned right in its column, text wrapping square around it.
#: CT_Anchor fixes the child order: simplePos, positionH, positionV, extent, a wrap
#: element, docPr, cNvGraphicFramePr, graphic. The last four move over from the inline.
ANCHOR_XML = (
    '<wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
    ' distT="0" distB="0" distL="114300" distR="114300" simplePos="0" relativeHeight="251658240"'
    ' behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
    '<wp:simplePos x="0" y="0"/>'
    '<wp:positionH relativeFrom="column"><wp:align>right</wp:align></wp:positionH>'
    '<wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>'
    "</wp:anchor>"
)

#: Columns narrow enough to read in a portrait page.
TABLE_COLUMNS = ("id", "first_name", "last_name", "city", "country")

#: Paragraphs per page of `docx_pages`: three of at most 378 words leave room on the page.
PAGED_PARAGRAPHS = 3
HEADER_TEXT = "loremfile.dev sample header"
#: The field code Word writes for a table of contents of headings 1 and 2, with hyperlinks.
TOC_INSTRUCTION = ' TOC \\o "1-2" \\h \\z \\u '


def _epoch(ctx: GeneratorContext) -> dt.datetime:
    """The fixed epoch, as an instance of whatever ``datetime.datetime`` now is.

    Built on every call rather than stored as a module constant. Inside the determinism
    guard ``datetime.datetime`` is a stand-in subclass, and python-docx checks its
    argument with ``isinstance(value, datetime.datetime)`` resolved through the module —
    so a real datetime built at import time is rejected with the genuinely confusing
    ``property requires <type 'datetime.datetime'> object, got <class 'datetime.datetime'>``.
    Building it here means the value is always the class currently installed.
    """
    return dt.datetime.fromtimestamp(ctx.epoch, tz=dt.UTC).replace(tzinfo=None)


def _plate(ctx: GeneratorContext, index: int, side: int = PLATE_SIDE) -> bytes:
    """One incompressible seeded-noise PNG, so a sized document is honestly sized."""
    needed = side * side * 3
    noise = ctx.stream(needed + index + 1)[index : index + needed]
    image = Image.frombytes("RGB", (side, side), noise)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=6)
    return buffer.getvalue()


# --- docx ------------------------------------------------------------------


def _new_document(ctx: GeneratorContext) -> docx.document.Document:
    document = docx.Document()
    core = document.core_properties
    core.author = core.last_modified_by = AUTHOR
    core.title = TITLE
    core.created = core.modified = _epoch(ctx)
    core.revision = 1
    core.language = "en-GB"
    return document


def _save_docx(document: docx.document.Document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return zipnorm.normalize(buffer.getvalue())


@generator()
def docx_basic(ctx: GeneratorContext, *, paragraphs: int = 6, heading: bool = True) -> bytes:
    """Lorem Ipsum in the default Word styles, no embedded media."""
    document = _new_document(ctx)
    if heading:
        document.add_heading("Loremfile sample document", level=1)
    rng = ctx.rng
    for _ in range(paragraphs):
        document.add_paragraph(lorem.paragraph(rng))
    return _save_docx(document)


@generator()
def docx_with_images(ctx: GeneratorContext, *, images: list[str]) -> bytes:
    """Embeds published image fixtures, read through ``ctx.dependency``."""
    document = _new_document(ctx)
    document.add_heading("Images", level=1)
    rng = ctx.rng
    for path in images:
        document.add_paragraph(lorem.paragraph(rng))
        document.add_picture(io.BytesIO(ctx.dependency(path)), width=Inches(3.0))
    return _save_docx(document)


@generator()
def docx_with_table(ctx: GeneratorContext, *, rows: int = 10) -> bytes:
    """One table of the shared people dataset, with a header row."""
    document = _new_document(ctx)
    document.add_heading("People", level=1)
    people = ctx.dataset("people", rows)
    table = document.add_table(rows=1, cols=len(TABLE_COLUMNS))
    table.style = "Table Grid"
    for cell, column in zip(table.rows[0].cells, TABLE_COLUMNS, strict=True):
        cell.text = column
        cell.paragraphs[0].runs[0].font.bold = True
    for person in people:
        cells = table.add_row().cells
        for cell, column in zip(cells, TABLE_COLUMNS, strict=True):
            cell.text = str(person[column])
    return _save_docx(document)


@generator(parallel_safe=False)
def docx_tracked_changes(ctx: GeneratorContext) -> bytes:
    """One deletion, one insertion and one anchored comment, with fixed revision metadata."""
    document = _new_document(ctx)
    document.add_heading("Tracked changes", level=1)
    paragraph = document.add_paragraph("The delivery status is ")
    for kind, number, text in (("del", 1, "cancelled"), ("ins", 2, "confirmed")):
        revision = OxmlElement(f"w:{kind}")
        revision.set(qn("w:id"), str(number))
        revision.set(qn("w:author"), AUTHOR)
        revision.set(qn("w:date"), "2020-01-01T00:00:00Z")
        run = OxmlElement("w:r")
        value = OxmlElement("w:delText" if kind == "del" else "w:t")
        value.text = text
        run.append(value)
        revision.append(run)
        paragraph._p.append(revision)
    paragraph.add_run(".")
    anchor = document.add_paragraph().add_run("Review the updated delivery status.")
    comment = document.add_comment(
        anchor, "The current status is confirmed.", author=AUTHOR, initials="LF"
    )
    comment._element.set(qn("w:date"), "2020-01-01T00:00:00Z")
    track = OxmlElement("w:trackRevisions")
    # CT_Settings places trackRevisions before defaultTabStop. The pinned template
    # contains that successor; appending at the end creates out-of-order settings.
    document.settings.element.insert_element_before(track, "w:defaultTabStop")
    return _save_docx(document)


@generator()
def docx_anchored_image(ctx: GeneratorContext, *, image: str) -> bytes:
    """One published JPEG anchored to a paragraph, floating right of the text, with alt text.

    python-docx writes only inline pictures, so the inline drawing it makes is moved into a
    `wp:anchor`. An extractor that walks inline shapes alone never sees this one.
    """
    document = _new_document(ctx)
    document.add_heading("Anchored image", level=1)
    rng = ctx.rng
    paragraph = document.add_paragraph()
    picture = paragraph.add_run().add_picture(io.BytesIO(ctx.dependency(image)), width=Inches(2.5))
    inline = picture._inline
    inline.docPr.set("descr", ANCHORED_ALT_TEXT)
    anchor = etree.fromstring(ANCHOR_XML)
    anchor.append(inline.extent)
    anchor.append(OxmlElement("wp:wrapSquare", attrs={"wrapText": "bothSides"}))
    for child in list(inline):
        if child.tag in {qn("wp:docPr"), qn("wp:cNvGraphicFramePr"), qn("a:graphic")}:
            anchor.append(child)
    inline.getparent().replace(inline, anchor)
    paragraph.add_run(lorem.paragraph(rng))
    for _ in range(2):
        document.add_paragraph(lorem.paragraph(rng))
    return _save_docx(document)


def _paged_body(document: docx.document.Document, rng: random.Random, pages: int) -> None:
    """`pages` sections, each a heading and three paragraphs, each after the first starting
    on a new page by `w:pageBreakBefore`. .docx stores no page count of its own, so the
    forced breaks are what make "N pages" true in every renderer. A section is at most 378
    words (three paragraphs of seven 18-word sentences), under a page, so none runs over."""
    for number in range(1, pages + 1):
        heading = document.add_heading(f"Page {number}", level=1)
        if number > 1:
            heading.paragraph_format.page_break_before = True
        for _ in range(PAGED_PARAGRAPHS):
            document.add_paragraph(lorem.paragraph(rng))


@generator()
def docx_pages(ctx: GeneratorContext, *, pages: int) -> bytes:
    """`pages` pages of Lorem Ipsum, each started by a forced page break."""
    document = _new_document(ctx)
    _paged_body(document, ctx.rng, pages)
    return _save_docx(document)


def _add_field(paragraph: Paragraph, instruction: str, cached: str) -> None:
    """A simple field (`PAGE`, `NUMPAGES`) with the value a renderer would show."""
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), f" {instruction} ")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = cached
    run.append(text)
    field.append(run)
    paragraph._p.append(field)


@generator()
def docx_headers_footers(ctx: GeneratorContext, *, pages: int) -> bytes:
    """A header on every page and a footer with PAGE and NUMPAGES fields."""
    document = _new_document(ctx)
    section = document.sections[0]
    section.header.is_linked_to_previous = False
    section.header.paragraphs[0].text = HEADER_TEXT
    section.footer.is_linked_to_previous = False
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("Page ")
    _add_field(footer, "PAGE", "1")
    footer.add_run(" of ")
    _add_field(footer, "NUMPAGES", str(pages))
    _paged_body(document, ctx.rng, pages)
    return _save_docx(document)


#: The elements CT_Settings puts after `updateFields`; it goes before the first one present.
UPDATE_FIELDS_SUCCESSORS = ("w:hdrShapeDefaults", "w:footnotePr", "w:endnotePr", "w:compat")


def _toc_styles(document: docx.document.Document) -> None:
    """The two paragraph styles Word gives a table of contents, which the default template
    lacks: entries in `toc 1` and `toc 2` with a dotted right-aligned tab for the page."""
    for level in (1, 2):
        style = document.styles.add_style(f"toc {level}", WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = document.styles["Normal"]
        style.paragraph_format.left_indent = Inches(0.25 * (level - 1))
        style.paragraph_format.tab_stops.add_tab_stop(
            Inches(6.0), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS
        )


def _field_char(kind: str) -> object:
    run = OxmlElement("w:r")
    mark = OxmlElement("w:fldChar")
    mark.set(qn("w:fldCharType"), kind)
    run.append(mark)
    return run


@generator()
def docx_toc(ctx: GeneratorContext, *, chapters: int, sections: int, toc: bool = True) -> bytes:
    """Headings behind a table-of-contents field that carries its entries.

    Every chapter starts a page and the contents take the first, so chapter `n` is on page
    `n + 1` and the cached entries say so. A reader that does not update fields still sees
    the entries; Word updates them on open (`updateFields`).
    """
    document = _new_document(ctx)
    rng = ctx.rng
    _toc_styles(document)
    outline: list[tuple[int, str, int]] = []
    body: list[tuple[int, str, str]] = []
    for chapter in range(1, chapters + 1):
        title = f"Chapter {chapter}: {' '.join(lorem.words(rng, 2)).capitalize()}"
        outline.append((1, title, chapter + 1))
        body.append((1, title, f"{lorem.sentence(rng)} {lorem.sentence(rng)}"))
        for section in range(1, sections + 1):
            heading = f"{chapter}.{section} {' '.join(lorem.words(rng, 2)).capitalize()}"
            outline.append((2, heading, chapter + 1))
            body.append((2, heading, f"{lorem.sentence(rng)} {lorem.sentence(rng)}"))

    if toc:
        document.add_paragraph("Contents", style="TOC Heading")
        for index, (level, text, page) in enumerate(outline):
            entry = document.add_paragraph(style=f"toc {level}")
            if index == 0:
                entry._p.append(_field_char("begin"))
                instruction = OxmlElement("w:r")
                code = OxmlElement("w:instrText")
                code.set(qn("xml:space"), "preserve")
                code.text = TOC_INSTRUCTION
                instruction.append(code)
                entry._p.append(instruction)
                entry._p.append(_field_char("separate"))
            entry.add_run(f"{text}\t{page}")
            if index == len(outline) - 1:
                entry._p.append(_field_char("end"))
        update = OxmlElement("w:updateFields")
        update.set(qn("w:val"), "true")
        document.settings.element.insert_element_before(update, *UPDATE_FIELDS_SUCCESSORS)

    for level, text, paragraph in body:
        heading = document.add_heading(text, level=level)
        if level == 1:
            heading.paragraph_format.page_break_before = True
        document.add_paragraph(paragraph)
    return _save_docx(document)


#: The reviewers of `docx_comments`: (author, initials).
REVIEWERS = ((AUTHOR, "LF"), ("Second reviewer", "SR"))


@generator()
def docx_comments(ctx: GeneratorContext, *, comments: int) -> bytes:
    """Comments from two authors, each anchored to the first sentence of its paragraph."""
    document = _new_document(ctx)
    document.add_heading("Comments", level=1)
    rng = ctx.rng
    for index in range(comments):
        paragraph = document.add_paragraph()
        anchor = paragraph.add_run(lorem.sentence(rng))
        paragraph.add_run(f" {lorem.paragraph(rng)}")
        author, initials = REVIEWERS[index % len(REVIEWERS)]
        comment = document.add_comment(
            anchor, lorem.sentence(rng), author=author, initials=initials
        )
        comment._element.set(qn("w:date"), "2020-01-01T00:00:00Z")
    return _save_docx(document)


@generator()
def docx_multilingual(ctx: GeneratorContext, *, scripts: list[str]) -> bytes:
    """One paragraph per script, then emoji and combining marks, Arabic and Hebrew right to left."""
    document = _new_document(ctx)
    document.add_heading("Multilingual text", level=1)
    rng = ctx.rng
    document.add_paragraph(f"Latin: {lorem.sentence(rng)}")
    for script in scripts:
        paragraph = document.add_paragraph()
        paragraph.add_run(f"{script.capitalize()}: ")
        text = paragraph.add_run(lorem.pseudo_text(rng, script, 8))
        if script in lorem.RTL_SCRIPTS:
            paragraph._p.get_or_add_pPr().append(OxmlElement("w:bidi"))
            text.font.rtl = True
    document.add_paragraph(f"Emoji: {lorem.emoji_run(rng, 12)}")
    document.add_paragraph("Combining marks: a\u0301 e\u0300 o\u0302 n\u0303 u\u0308 c\u0327")
    return _save_docx(document)


@generator(parallel_safe=False)
def docx_sized(ctx: GeneratorContext, *, size: int) -> bytes:
    """One lorem paragraph per embedded noise plate, fitted to ``size`` (docs/05 §6)."""

    def make(plates: int) -> bytes:
        document = _new_document(ctx)
        document.add_heading("Loremfile sized document", level=1)
        rng = ctx.rng
        for index in range(plates):
            document.add_paragraph(lorem.paragraph(rng))
            document.add_picture(io.BytesIO(_plate(ctx, index)), width=Inches(3.0))
        return _save_docx(document)

    start = max(1, round(size / APPROX_PLATE_BYTES))
    _, payload = fit(size, APPROX_TOLERANCE, make, n0=start, n_min=1, n_max=1000)
    return payload


# --- xlsx ------------------------------------------------------------------


def _new_workbook(ctx: GeneratorContext) -> Workbook:
    workbook = Workbook()
    properties = workbook.properties
    properties.creator = properties.lastModifiedBy = AUTHOR
    properties.title = TITLE
    properties.created = properties.modified = _epoch(ctx)
    return workbook


def _save_workbook(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    # Not cosmetic: openpyxl stamps worksheet entries from a temp file's mtime.
    return zipnorm.normalize(buffer.getvalue())


def _cell_value(value: object) -> object:
    """Coerce a dataset value into something Excel can hold, losing as little as possible.

    The shared people dataset carries three things a worksheet cell cannot take: a list
    (`tags`), a timezone-aware datetime (`signup_at` — Excel has no concept of one) and
    a Decimal. The list is joined, the timezone dropped after conversion to UTC, and the
    Decimal left alone, which openpyxl writes as a number. Anything else is passed
    through, so a new dataset column fails loudly here rather than being silently
    stringified.
    """
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if isinstance(value, dt.datetime) and value.tzinfo is not None:
        return value.astimezone(dt.UTC).replace(tzinfo=None)
    return value


def _write_people(
    sheet: Worksheet, people: list[dict[str, Any]], *, autofilter: bool = False
) -> None:
    columns = list(people[0])
    sheet.append(columns)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for person in people:
        sheet.append([_cell_value(person[column]) for column in columns])
    for column, width in (("D", 30), ("F", 24), ("J", 20)):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"
    if autofilter:
        sheet.auto_filter.ref = sheet.dimensions


@generator(parallel_safe=False)
def xlsx_people(
    ctx: GeneratorContext, *, rows: int, sheets: int = 1, autofilter: bool = False
) -> bytes:
    """The shared people dataset, one row per record.

    With more than one sheet each holds the next `rows` records, so a reader that returns
    the wrong sheet shows it; three identical sheets would hide the mistake.
    """
    workbook = _new_workbook(ctx)
    first = workbook.active
    if first is None:  # pragma: no cover - openpyxl always creates one
        raise RuntimeError("the new workbook has no active sheet")
    first.title = "People" if sheets == 1 else "People 1"
    people = ctx.dataset("people", rows * sheets)
    _write_people(first, people[:rows], autofilter=autofilter)
    for index in range(2, sheets + 1):
        extra = workbook.create_sheet(f"People {index}")
        _write_people(extra, people[(index - 1) * rows : index * rows], autofilter=autofilter)
    return _save_workbook(workbook)


@generator()
def xlsx_merged_cells(ctx: GeneratorContext) -> bytes:
    """A title across four columns, two regions each spanning three rows, and a 2 x 2 block."""
    workbook = _new_workbook(ctx)
    sheet = workbook.active
    if sheet is None:  # pragma: no cover
        raise RuntimeError("the new workbook has no active sheet")
    sheet.title = "Sales"
    sheet["A1"] = "Regional sales report"
    sheet["A1"].font = Font(bold=True, size=14)
    sheet["A1"].alignment = Alignment(horizontal="center")
    sheet.merge_cells("A1:D1")
    for column, name in enumerate(("Region", "Quarter", "Units", "Revenue"), start=1):
        sheet.cell(row=2, column=column, value=name).font = Font(bold=True)
    row = 3
    for region_index, region in enumerate(("North region", "South region")):
        sheet.cell(row=row, column=1, value=region).alignment = Alignment(vertical="center")
        sheet.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=1)
        for quarter_index, quarter in enumerate(("Q1", "Q2", "Q3")):
            units = 100 + (region_index * 3 + quarter_index) * 37 % 90
            sheet.cell(row=row, column=2, value=quarter)
            sheet.cell(row=row, column=3, value=units)
            sheet.cell(row=row, column=4, value=units * 12.5)
            row += 1
    sheet["F2"] = "Merged 2 by 2 block"
    sheet["F2"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.merge_cells("F2:G3")
    sheet.column_dimensions["A"].width = 16
    sheet.column_dimensions["F"].width = 22
    return _save_workbook(workbook)


@generator()
def xlsx_with_chart(ctx: GeneratorContext) -> bytes:
    """Four quarters of signups and a native column chart that reads them."""
    workbook = _new_workbook(ctx)
    sheet = workbook.active
    if sheet is None:  # pragma: no cover
        raise RuntimeError("the new workbook has no active sheet")
    sheet.title = "Signups"
    sheet.append(["quarter", "signups"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for quarter, signups in zip(CHART_CATEGORIES, CHART_VALUES, strict=True):
        sheet.append([quarter, signups])
    last = len(CHART_CATEGORIES) + 1
    chart = BarChart()
    chart.type = "col"
    chart.title = "Quarterly signups"
    chart.x_axis.title = "Quarter"
    chart.y_axis.title = "Signups"
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=last), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=last))
    # openpyxl 3.1 writes the axes as deleted unless told otherwise: the chart would open
    # in Excel as bars with no labels.
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.legend = None
    sheet.add_chart(chart, "D2")
    return _save_workbook(workbook)


@generator()
def xlsx_with_images(ctx: GeneratorContext, *, images: list[str]) -> bytes:
    """Published image fixtures, read through ``ctx.dependency``, each under a caption."""
    workbook = _new_workbook(ctx)
    sheet = workbook.active
    if sheet is None:  # pragma: no cover
        raise RuntimeError("the new workbook has no active sheet")
    sheet.title = "Images"
    sheet["A1"] = "Embedded images"
    sheet["A1"].font = Font(bold=True)
    rng = ctx.rng
    row = 3
    for path in images:
        sheet.cell(row=row, column=1, value=lorem.sentence(rng))
        picture = SheetImage(io.BytesIO(ctx.dependency(path)))
        sheet.add_image(picture, f"A{row + 1}")
        # A default row is 20 pixels tall; leave two rows between pictures.
        row += -(-picture.height // 20) + 3
    sheet.column_dimensions["A"].width = 40
    return _save_workbook(workbook)


@generator()
def xlsx_unicode(ctx: GeneratorContext, *, scripts: list[str]) -> bytes:
    """One row per script, then emoji and combining marks; Arabic and Hebrew read right to left."""
    workbook = _new_workbook(ctx)
    sheet = workbook.active
    if sheet is None:  # pragma: no cover
        raise RuntimeError("the new workbook has no active sheet")
    sheet.title = "Unicode"
    rng = ctx.rng
    sheet.append(["script", "text"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.append(["latin", lorem.sentence(rng)])
    for script in scripts:
        sheet.append([script, lorem.pseudo_text(rng, script, 8)])
        if script in lorem.RTL_SCRIPTS:
            sheet.cell(row=sheet.max_row, column=2).alignment = Alignment(
                horizontal="right", readingOrder=2
            )
    sheet.append(["emoji", lorem.emoji_run(rng, 12)])
    sheet.append(["combining marks", "a\u0301 e\u0300 o\u0302 n\u0303 u\u0308 c\u0327"])
    sheet.column_dimensions["A"].width = 18
    sheet.column_dimensions["B"].width = 60
    return _save_workbook(workbook)


def _inject_cached_values(data: bytes, sheet: str, cached: dict[str, object]) -> bytes:
    """Give every formula cell the value a spreadsheet application would cache.

    Without this, `load_workbook(data_only=True)` and pandas both read `None`: openpyxl
    writes the formula and an empty `<v/>`, and never computes anything. The value has to
    replace that placeholder — appending a second `<v>` leaves readers taking the first.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    root = etree.fromstring(parts[sheet])
    written: set[str] = set()
    for cell in root.iter(f"{{{SHEET_NS}}}c"):
        reference = cell.get("r")
        if reference not in cached:
            continue
        value = cached[reference]
        if isinstance(value, str):
            cell.set("t", "str")
        element = cell.find(f"{{{SHEET_NS}}}v")
        if element is None:
            element = etree.SubElement(cell, f"{{{SHEET_NS}}}v")
        element.text = str(value)
        written.add(reference)
    missing = sorted(set(cached) - written)
    if missing:
        raise ValueError(f"no formula cells at {missing} to cache values into")
    parts[sheet] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for name, payload in parts.items():
            target.writestr(name, payload)
    return zipnorm.normalize(out.getvalue())


@generator()
def xlsx_with_formulas(ctx: GeneratorContext, *, rows: int = 10) -> bytes:
    """SUM, AVERAGE, IF and VLOOKUP over an order table, with cached results."""
    workbook = _new_workbook(ctx)
    sheet = workbook.active
    if sheet is None:  # pragma: no cover
        raise RuntimeError("the new workbook has no active sheet")
    sheet.title = "Orders"
    sheet.append(["item", "quantity", "unit_price", "total"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    quantities = [(index % 7) + 1 for index in range(rows)]
    prices = [round(2.5 + index * 1.25, 2) for index in range(rows)]
    for index in range(rows):
        row = index + 2
        sheet.append([f"item-{index + 1:03d}", quantities[index], prices[index]])
        sheet.cell(row=row, column=4).value = f"=B{row}*C{row}"

    last = rows + 1
    totals = [round(q * p, 2) for q, p in zip(quantities, prices, strict=True)]
    grand = round(sum(totals), 2)
    mean = round(grand / rows, 10)
    lookup_row = min(3, rows)

    sheet["F1"] = "quantity total"
    sheet["F2"] = "mean line total"
    sheet["F3"] = "is a large order"
    sheet["F4"] = f"unit price of item-{lookup_row:03d}"
    sheet["G1"] = f"=SUM(B2:B{last})"
    sheet["G2"] = f"=AVERAGE(D2:D{last})"
    sheet["G3"] = f'=IF(G1>{LARGE_ORDER},"yes","no")'
    sheet["G4"] = f'=VLOOKUP("item-{lookup_row:03d}",A2:C{last},3,FALSE)'
    sheet.column_dimensions["F"].width = 26

    cached: dict[str, object] = {
        "G1": sum(quantities),
        "G2": mean,
        "G3": "yes" if sum(quantities) > LARGE_ORDER else "no",
        "G4": prices[lookup_row - 1],
    }
    for index in range(rows):
        cached[f"D{index + 2}"] = totals[index]
    return _inject_cached_values(_save_workbook(workbook), "xl/worksheets/sheet1.xml", cached)


@generator()
def xlsx_multisheet_formulas(ctx: GeneratorContext, *, rows: int = 10) -> bytes:
    """Three sheets, the third summarising the other two with formulas that read across.

    The order sheet's name holds a space, so every reference to it must be quoted
    (`'Order lines'!F2`): the case a formula reader that splits on `!` gets wrong.
    """
    people = ctx.dataset("people", rows)
    workbook = _new_workbook(ctx)
    first = workbook.active
    if first is None:  # pragma: no cover
        raise RuntimeError("the new workbook has no active sheet")
    first.title = "People"
    _write_people(first, people)

    orders = workbook.create_sheet("Order lines")
    orders.append(["order", "person_id", "item", "quantity", "unit_price", "total"])
    for cell in orders[1]:
        cell.font = Font(bold=True)
    # Repeats some customers and skips others, so COUNTIF has something to count.
    customers = [people[(index * 3) % 7]["id"] for index in range(rows)]
    quantities = [(index % 7) + 1 for index in range(rows)]
    prices = [round(2.5 + index * 1.25, 2) for index in range(rows)]
    for index in range(rows):
        row = index + 2
        orders.append(
            [
                f"ord-{index + 1:03d}",
                customers[index],
                f"item-{index + 1:03d}",
                quantities[index],
                prices[index],
            ]
        )
        orders.cell(row=row, column=6).value = f"=D{row}*E{row}"
    totals = [round(q * p, 2) for q, p in zip(quantities, prices, strict=True)]

    last = rows + 1
    lines = "'Order lines'"
    by_id = {person["id"]: person for person in people}
    summary = workbook.create_sheet("Summary")
    summary.append(["measure", "value"])
    for cell in summary[1]:
        cell.font = Font(bold=True)
    measures: list[tuple[str, str, object]] = [
        ("people", f"=COUNTA(People!A2:A{last})", rows),
        ("order lines", f"=COUNTA({lines}!A2:A{last})", rows),
        ("quantity total", f"=SUM({lines}!D2:D{last})", sum(quantities)),
        ("revenue", f"=SUM({lines}!F2:F{last})", round(sum(totals), 2)),
        ("mean order line", f"=AVERAGE({lines}!F2:F{last})", round(sum(totals) / rows, 10)),
        (
            "first order's customer",
            f"=VLOOKUP({lines}!B2,People!A2:B{last},2,FALSE)",
            by_id[customers[0]]["first_name"],
        ),
        (
            f"order lines for person {people[0]['id']}",
            f"=COUNTIF({lines}!B2:B{last},People!A2)",
            customers.count(people[0]["id"]),
        ),
    ]
    for label, formula, _ in measures:
        summary.append([label, formula])
    summary.column_dimensions["A"].width = 28

    data = _save_workbook(workbook)
    data = _inject_cached_values(
        data, "xl/worksheets/sheet2.xml", {f"F{i + 2}": totals[i] for i in range(rows)}
    )
    return _inject_cached_values(
        data,
        "xl/worksheets/sheet3.xml",
        {f"B{i + 2}": value for i, (_, _, value) in enumerate(measures)},
    )


@generator()
def xlsx_with_types(ctx: GeneratorContext) -> bytes:
    """One column per Excel type and number format, including the awkward ones."""
    workbook = _new_workbook(ctx)
    sheet = workbook.active
    if sheet is None:  # pragma: no cover
        raise RuntimeError("the new workbook has no active sheet")
    sheet.title = "Types"
    moment = _epoch(ctx)

    rows: list[tuple[str, Any, str | None]] = [
        ("text", "Lorem ipsum", None),
        ("integer", 42, "0"),
        ("float", 3.14159, "0.00000"),
        ("negative", -1234.5, "#,##0.00"),
        ("boolean true", True, None),
        ("boolean false", False, None),
        ("date", moment.date(), "yyyy-mm-dd"),
        ("time", dt.time(13, 45, 30), "hh:mm:ss"),
        ("datetime", moment, "yyyy-mm-dd hh:mm:ss"),
        ("percentage", 0.4275, "0.00%"),
        ("currency", 1999.99, '"£"#,##0.00'),
        ("scientific", 0.000000123, "0.00E+00"),
        ("text that looks numeric", "007", "@"),
        ("text that looks like a date", "2020-01-01", "@"),
        ("leading apostrophe kept", "+44 20 7946 0000", "@"),
        ("empty", None, None),
    ]
    sheet.append(["label", "value"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for label, value, number_format in rows:
        sheet.append([label, value])
        cell = sheet.cell(row=sheet.max_row, column=2)
        if number_format:
            cell.number_format = number_format
        cell.alignment = Alignment(horizontal="left")
    sheet.column_dimensions["A"].width = 28
    sheet.column_dimensions["B"].width = 24
    return _save_workbook(workbook)


@generator(parallel_safe=False)
def xlsx_sized(ctx: GeneratorContext, *, size: int) -> bytes:
    """One people row per embedded noise plate, fitted to ``size`` (docs/05 §6)."""

    def make(plates: int) -> bytes:
        workbook = _new_workbook(ctx)
        sheet = workbook.active
        if sheet is None:  # pragma: no cover
            raise RuntimeError("the new workbook has no active sheet")
        sheet.title = "People"
        _write_people(sheet, ctx.dataset("people", max(plates, 1)))
        images = workbook.create_sheet("Plates")
        for index in range(plates):
            picture = SheetImage(io.BytesIO(_plate(ctx, index)))
            images.add_image(picture, f"A{index * 14 + 1}")
        return _save_workbook(workbook)

    start = max(1, round(size / APPROX_PLATE_BYTES))
    _, payload = fit(size, APPROX_TOLERANCE, make, n0=start, n_min=1, n_max=1000)
    return payload


# --- pptx ------------------------------------------------------------------


#: python-pptx's built-in template is 4:3 (10 x 7.5 inches). Every fixture here but one is
#: widescreen, which is what current PowerPoint and Keynote produce; the 4:3 shape is its
#: own named fixture (`aspect-4-3-5slides.pptx`, 1.10.0) rather than a silent default.
SLIDE_16_9 = (PptxInches(13.333), PptxInches(7.5))
#: The 4:3 size PowerPoint used before 2013, which older decks and templates still carry.
SLIDE_4_3 = (PptxInches(10), PptxInches(7.5))
SLIDE_SIZES = {"16:9": SLIDE_16_9, "4:3": SLIDE_4_3}
#: A chart's numbers, fixed so the embedded workbook holds the same cells every build.
CHART_CATEGORIES = ("Q1", "Q2", "Q3", "Q4")
CHART_VALUES = (12.0, 19.0, 7.0, 15.0)


def _new_presentation(ctx: GeneratorContext, aspect: str = "16:9") -> PresentationDocument:
    presentation = Presentation()
    presentation.slide_width, presentation.slide_height = SLIDE_SIZES[aspect]
    core = presentation.core_properties
    core.author = core.last_modified_by = AUTHOR
    core.title = TITLE
    core.created = core.modified = _epoch(ctx)
    core.revision = 1
    return presentation


def _save_presentation(presentation: PresentationDocument) -> bytes:
    buffer = io.BytesIO()
    presentation.save(buffer)
    return zipnorm.normalize(buffer.getvalue())


def _title_and_body(presentation: PresentationDocument, title: str, body: str) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = title
    frame = slide.placeholders[1].text_frame
    frame.text = body
    frame.paragraphs[0].font.size = Pt(18)


@generator()
def pptx_basic(
    ctx: GeneratorContext,
    *,
    slides: int = 1,
    aspect: str = "16:9",
    table_rows: int = 0,
    chart: bool = False,
    hidden: tuple[int, ...] = (),
    notes: bool = False,
    images: tuple[str, ...] = (),
) -> bytes:
    """Title-and-content slides of Lorem Ipsum, 16:9 unless `aspect` says 4:3.

    `table_rows` adds a slide with a native table of that many people (plus a header row),
    `chart` a slide with a native column chart, `images` a slide for each published image
    fixture named, `notes` a speaker note on each title-and-content slide, and `hidden`
    marks those slides (1-based) hidden, the `show="0"` a converter that renders every slide
    gets wrong.
    """
    presentation = _new_presentation(ctx, aspect)
    rng = ctx.rng
    for index in range(slides):
        _title_and_body(presentation, f"Slide {index + 1}", lorem.paragraph(rng))
        if notes:
            presentation.slides[index].notes_slide.notes_text_frame.text = lorem.sentence(rng)
    if table_rows:
        _table_slide(presentation, ctx.dataset("people", table_rows))
    if chart:
        _chart_slide(ctx, presentation)
    for number, path in enumerate(images, start=1):
        slide = presentation.slides.add_slide(presentation.slide_layouts[5])
        slide.shapes.title.text = f"Image {number}"
        slide.shapes.add_picture(
            io.BytesIO(ctx.dependency(path)), PptxInches(1), PptxInches(1.8), width=PptxInches(4)
        )
    for number in hidden:
        # python-pptx has no API for it: a hidden slide is `show="0"` on its <p:sld>.
        presentation.slides[number - 1]._element.set("show", "0")
    return _save_presentation(presentation)


def _table_slide(presentation: PresentationDocument, people: list[dict[str, Any]]) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "People"
    columns = ("first_name", "last_name", "city", "country")
    shape = slide.shapes.add_table(
        len(people) + 1,
        len(columns),
        PptxInches(0.5),
        PptxInches(1.8),
        PptxInches(9),
        PptxInches(3),
    )
    for col, name in enumerate(columns):
        shape.table.cell(0, col).text = name
        for row, person in enumerate(people, 1):
            shape.table.cell(row, col).text = str(person[name])


def _chart_slide(ctx: GeneratorContext, presentation: PresentationDocument) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "Quarterly signups"
    data = CategoryChartData()
    data.categories = CHART_CATEGORIES
    data.add_series("Signups", CHART_VALUES)
    frame = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        PptxInches(0.5),
        PptxInches(1.8),
        PptxInches(9),
        PptxInches(4.5),
        data,
    )
    workbook = frame.chart.part.chart_workbook
    workbook.update_from_xlsx_blob(_pinned_workbook(ctx, workbook.xlsx_part.blob))


def _pinned_workbook(ctx: GeneratorContext, blob: bytes) -> bytes:
    """The chart's embedded workbook with its two core-properties dates set to the epoch.

    XlsxWriter, which python-pptx writes chart data through, stamps the wall clock into
    `docProps/core.xml` from below the layer the determinism guard patches: two builds a
    minute apart differed there and nowhere else (docs/06 §4, found by the 1.10.0 spike).
    """
    stamp = _epoch(ctx).strftime("%Y-%m-%dT%H:%M:%SZ")
    with zipfile.ZipFile(io.BytesIO(blob)) as source:
        members = {name: source.read(name) for name in source.namelist()}
    core = members["docProps/core.xml"].decode("utf-8")
    members["docProps/core.xml"] = re.sub(
        r"(<dcterms:(?:created|modified)\b[^>]*>)[^<]*", rf"\g<1>{stamp}", core
    ).encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for name, payload in members.items():
            target.writestr(name, payload)
    return zipnorm.normalize(out.getvalue())


@generator(parallel_safe=False)
def pptx_sized(ctx: GeneratorContext, *, size: int) -> bytes:
    """One slide per embedded noise plate, fitted to ``size`` (docs/05 §6)."""

    def make(plates: int) -> bytes:
        presentation = _new_presentation(ctx)
        rng = ctx.rng
        for index in range(plates):
            slide = presentation.slides.add_slide(presentation.slide_layouts[5])
            slide.shapes.title.text = f"Plate {index + 1}"
            slide.shapes.add_picture(
                io.BytesIO(_plate(ctx, index)),
                PptxInches(1),
                PptxInches(1.8),
                PptxInches(3),
                PptxInches(3),
            )
            notes = slide.notes_slide.notes_text_frame
            notes.text = lorem.sentence(rng)
        return _save_presentation(presentation)

    start = max(1, round(size / APPROX_PLATE_BYTES))
    _, payload = fit(size, APPROX_TOLERANCE, make, n0=start, n_min=1, n_max=1000)
    return payload


# --- rtf -------------------------------------------------------------------

#: RTF is a plain-text format, so these fixtures are written by hand rather than by a
#: library. Every byte is ASCII: non-ASCII characters would need \u escapes, and these
#: two fixtures deliberately stay in the range every reader agrees on.
RTF_HEADER = r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\froman Times New Roman;}}"


def _rtf_escape(text: str) -> str:
    """Escape RTF's three special characters, and refuse anything non-ASCII."""
    if not text.isascii():
        raise ValueError(f"RTF fixtures stay in ASCII; got {text!r}")
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


@generator()
def rtf_simple(ctx: GeneratorContext, *, paragraphs: int = 3) -> bytes:
    """Plain paragraphs of Lorem Ipsum, hand-written RTF."""
    rng = ctx.rng
    body = [r"\pard\sa200\sl276\slmult1\f0\fs24 " + _rtf_escape(lorem.paragraph(rng)) + r"\par"]
    for _ in range(paragraphs - 1):
        body.append(r"\pard\sa200 " + _rtf_escape(lorem.paragraph(rng)) + r"\par")
    return (RTF_HEADER + "\n" + "\n".join(body) + "\n}").encode("ascii")


#: A second font and a colour table, for `rtf_formatted`. Colour 0 is "auto", as RTF says.
RTF_FORMATTED_HEADER = (
    r"{\rtf1\ansi\ansicpg1252\deff0"
    r"{\fonttbl{\f0\froman Times New Roman;}{\f1\fmodern Courier New;}}"
    r"{\colortbl;\red0\green0\blue0;\red192\green0\blue0;\red0\green0\blue192;}"
)
#: A single-line border on all four sides of a table cell.
RTF_CELL_EDGES = (
    r"\clbrdrt\brdrs\brdrw10\clbrdrl\brdrs\brdrw10\clbrdrb\brdrs\brdrw10\clbrdrr\brdrs\brdrw10"
)
RTF_TABLE_COLUMNS = ("first_name", "last_name", "city")
RTF_CELL_WIDTH = 3000


def _rtf_row(cells: list[str], *, bold: bool = False) -> str:
    """One table row: the cell edges, then each cell's paragraph closed by `\\cell`."""
    edges = "".join(
        RTF_CELL_EDGES + rf"\cellx{RTF_CELL_WIDTH * (index + 1)}" for index in range(len(cells))
    )
    on, off = (r"\b ", r"\b0 ") if bold else ("", "")
    body = "".join(rf"\pard\intbl\f0\fs24 {on}{_rtf_escape(text)}{off}\cell " for text in cells)
    return rf"\trowd\trgaph108\trleft0{edges}" + "\n" + body + r"\row"


@generator()
def rtf_formatted(ctx: GeneratorContext, *, table_rows: int = 4) -> bytes:
    """Bold, italic, underline, colour, size and a second font, then a bordered table."""
    rng = ctx.rng

    def sentence() -> str:
        return _rtf_escape(lorem.sentence(rng))

    runs = [
        sentence(),
        r"{\b " + sentence() + "}",
        r"{\i " + sentence() + "}",
        r"{\ul " + sentence() + "}",
        r"{\cf2 " + sentence() + "}",
        r"{\cf3\fs32 " + sentence() + "}",
        r"{\f1 " + sentence() + "}",
    ]
    body = [
        r"\pard\qc\sa200\f0\fs36\b Formatted sample\b0\fs24\par",
        r"\pard\sa200\f0\fs24 " + " ".join(runs) + r"\par",
    ]
    if table_rows:
        body.append(_rtf_row(list(RTF_TABLE_COLUMNS), bold=True))
        for person in ctx.dataset("people", table_rows):
            body.append(_rtf_row([str(person[column]) for column in RTF_TABLE_COLUMNS]))
        # A table has to be followed by a paragraph, or Word has nowhere to put the cursor.
        body.append(r"\pard\sa200 The table above holds records of the shared people dataset.\par")
    return (RTF_FORMATTED_HEADER + "\n" + "\n".join(body) + "\n}").encode("ascii")


# --- epub ------------------------------------------------------------------

#: EPUB 3 needs these three files plus the content documents (OCF 3.0, EPUB 3.3).
EPUB_CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

#: Media types of the image fixtures an EPUB may embed, by extension.
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg"}

EPUB_CSS = """body { font-family: serif; line-height: 1.5; margin: 1em; }
h1 { font-size: 1.4em; }
"""


def _epub_chapter(number: int, title: str, paragraphs: list[str], figure: str = "") -> str:
    body = "\n".join(f"    <p>{paragraph}</p>" for paragraph in paragraphs)
    if figure:
        body += "\n" + figure
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="en" lang="en">
  <head>
    <title>{title}</title>
    <meta charset="utf-8"/>
    <link rel="stylesheet" type="text/css" href="style.css"/>
  </head>
  <body>
    <section epub:type="chapter" id="chapter-{number}">
    <h1>{title}</h1>
{body}
    </section>
  </body>
</html>
"""


@generator()
def epub3(
    ctx: GeneratorContext,
    *,
    chapters: int = 3,
    paragraphs: int = 4,
    images: tuple[str, ...] = (),
) -> bytes:
    """A valid EPUB 3 with a package document, a nav document and N chapters.

    Each published image fixture named in `images` goes in its own chapter, in order, with
    alt text and an item in the manifest.

    The identifier and the modification date are fixed rather than generated: an EPUB
    carries a `dcterms:modified` that would otherwise be the wall clock, and a UUID that
    would otherwise be random. Both are part of the published bytes forever.
    """
    rng = ctx.rng
    moment = _epoch(ctx).strftime("%Y-%m-%dT%H:%M:%SZ")
    identifier = "urn:uuid:" + ctx.stream(16).hex()

    titles = [f"Chapter {number}" for number in range(1, chapters + 1)]
    files: dict[str, bytes] = {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": EPUB_CONTAINER.encode("utf-8"),
        "EPUB/style.css": EPUB_CSS.encode("utf-8"),
    }
    image_items: list[str] = []
    for number, title in enumerate(titles, start=1):
        text = [lorem.paragraph(rng) for _ in range(paragraphs)]
        figure = ""
        if number <= len(images):
            path = images[number - 1]
            name = path.rsplit("/", 1)[1]
            files[f"EPUB/images/{name}"] = ctx.dependency(path)
            figure = (
                f'    <figure><img src="images/{name}" alt="Published fixture {path}"/></figure>'
            )
            image_items.append(
                f'    <item id="image-{number}" href="images/{name}" '
                f'media-type="{IMAGE_TYPES[name.rsplit(".", 1)[1]]}"/>'
            )
        files[f"EPUB/chapter-{number}.xhtml"] = _epub_chapter(number, title, text, figure).encode(
            "utf-8"
        )

    items = "\n".join(
        f'    <item id="chapter-{number}" href="chapter-{number}.xhtml" '
        f'media-type="application/xhtml+xml"/>'
        for number in range(1, chapters + 1)
    )
    if image_items:
        items += "\n" + "\n".join(image_items)
    spine = "\n".join(
        f'    <itemref idref="chapter-{number}"/>' for number in range(1, chapters + 1)
    )
    files["EPUB/package.opf"] = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id"
         xml:lang="en">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="pub-id">{identifier}</dc:identifier>
    <dc:title>Loremfile Sample Book</dc:title>
    <dc:language>en</dc:language>
    <dc:creator>{AUTHOR}</dc:creator>
    <dc:rights>CC0 1.0 Universal</dc:rights>
    <meta property="dcterms:modified">{moment}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="css" href="style.css" media-type="text/css"/>
{items}
  </manifest>
  <spine>
{spine}
  </spine>
</package>
""".encode()

    links = "\n".join(
        f'        <li><a href="chapter-{number}.xhtml">{title}</a></li>'
        for number, title in enumerate(titles, start=1)
    )
    files["EPUB/nav.xhtml"] = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="en" lang="en">
  <head><title>Contents</title><meta charset="utf-8"/></head>
  <body>
    <nav epub:type="toc" id="toc">
      <h1>Contents</h1>
      <ol>
{links}
      </ol>
    </nav>
  </body>
</html>
""".encode()

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    # epub=True puts `mimetype` first and stores it uncompressed, which OCF requires.
    return zipnorm.normalize(out.getvalue(), epub=True)


#: EPUB 2 content is XHTML 1.1: it has the doctype, and neither `epub:type` nor `<meta charset>`.
EPUB2_DOCTYPE = (
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" '
    '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
)
EPUB2_CONTAINER = EPUB_CONTAINER.replace("EPUB/package.opf", "OEBPS/content.opf")


def _epub2_chapter(number: int, title: str, paragraphs: list[str]) -> str:
    body = "\n".join(f"    <p>{paragraph}</p>" for paragraph in paragraphs)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
{EPUB2_DOCTYPE}
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
  <head>
    <title>{title}</title>
    <meta http-equiv="Content-Type" content="application/xhtml+xml; charset=utf-8"/>
    <link rel="stylesheet" type="text/css" href="style.css"/>
  </head>
  <body>
    <div id="chapter-{number}">
    <h1>{title}</h1>
{body}
    </div>
  </body>
</html>
"""


@generator()
def epub2(ctx: GeneratorContext, *, chapters: int = 3, paragraphs: int = 4) -> bytes:
    """A valid EPUB 2.0.1: an OPF with a spine pointing at an NCX, and no nav document.

    The identifier is derived from the fixture's seed and the date is a literal, as in
    `epub3`: both are part of the published bytes for good. The NCX repeats the identifier,
    which is the one thing a reader checks it against.
    """
    rng = ctx.rng
    digest = ctx.stream(16).hex()
    identifier = (
        f"urn:uuid:{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-a{digest[17:20]}-{digest[20:]}"
    )
    titles = [f"Chapter {number}" for number in range(1, chapters + 1)]
    files: dict[str, bytes] = {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": EPUB2_CONTAINER.encode("utf-8"),
        "OEBPS/style.css": EPUB_CSS.encode("utf-8"),
    }
    for number, title in enumerate(titles, start=1):
        text = [lorem.paragraph(rng) for _ in range(paragraphs)]
        files[f"OEBPS/chapter-{number}.xhtml"] = _epub2_chapter(number, title, text).encode("utf-8")

    items = "\n".join(
        f'    <item id="chapter-{number}" href="chapter-{number}.xhtml" '
        f'media-type="application/xhtml+xml"/>'
        for number in range(1, chapters + 1)
    )
    spine = "\n".join(
        f'    <itemref idref="chapter-{number}"/>' for number in range(1, chapters + 1)
    )
    files["OEBPS/content.opf"] = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="BookId">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="BookId" opf:scheme="UUID">{identifier}</dc:identifier>
    <dc:title>Loremfile Sample Book</dc:title>
    <dc:language>en</dc:language>
    <dc:creator opf:role="aut">{AUTHOR}</dc:creator>
    <dc:rights>CC0 1.0 Universal</dc:rights>
    <dc:date opf:event="modification">2020-01-01</dc:date>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
{items}
  </manifest>
  <spine toc="ncx">
{spine}
  </spine>
</package>
""".encode()

    points = "\n".join(
        f'    <navPoint id="navpoint-{number}" playOrder="{number}">\n'
        f"      <navLabel><text>{title}</text></navLabel>\n"
        f'      <content src="chapter-{number}.xhtml"/>\n'
        f"    </navPoint>"
        for number, title in enumerate(titles, start=1)
    )
    files["OEBPS/toc.ncx"] = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{identifier}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>Loremfile Sample Book</text></docTitle>
  <navMap>
{points}
  </navMap>
</ncx>
""".encode()

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return zipnorm.normalize(out.getvalue(), epub=True)
