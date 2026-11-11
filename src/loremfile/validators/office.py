"""Validators for docx, xlsx, pptx, rtf and epub (docs/06 §6 and §13).

Two independent readers, as docs/06 §6 requires. The writing library is never the only
opinion: every OOXML fixture is also read as a **zip archive** and checked against what
the format actually mandates — `[Content_Types].xml` present, the package relationships
present, the media parts really there. A file python-docx happily reopens can still be a
package Word refuses, because python-docx reads back its own conventions.

These validators assert **structure, not parseability** (docs/06 §13): that a table has
the rows it claims, that a formula cell carries a cached value a non-calculating reader
can use, that an EPUB's `mimetype` entry is first and stored uncompressed. Any of those
can be wrong in a file that opens without complaint.
"""

from __future__ import annotations

import io
import posixpath
import re
import unicodedata
import zipfile
from typing import Any

import docx
from lxml import etree
from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from pptx import Presentation

from loremfile.catalog import Fixture
from loremfile.validators import ValidationError, register
from loremfile.validators.text import text_props

#: Parts every OOXML package must carry, whatever the flavour.
OOXML_REQUIRED = ("[Content_Types].xml", "_rels/.rels")

#: A table that is only a header row, or only data, is a mistake in the generator.
MIN_TABLE_ROWS = 2

#: EPUB's Open Container Format requires exactly this, and readers rely on it.
EPUB_MIMETYPE = b"application/epub+zip"

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD_NAMESPACES = {"w": WORD_NS}
COMMENT_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
COMMENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
DRAWING_NAMESPACES = {
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
}
RELATIONSHIP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
#: What CT_Settings puts after `updateFields`: it may not come after any of them.
UPDATE_FIELDS_SUCCESSORS = ("hdrShapeDefaults", "footnotePr", "endnotePr", "compat")
FALSE_VALUES = {"0", "false", "off"}
#: A cell's `readingOrder` for right to left (0 is context, 1 left to right).
RIGHT_TO_LEFT = 2


def _word_xml(archive: zipfile.ZipFile, part: str) -> etree._Element:
    return etree.fromstring(
        archive.read(part), etree.XMLParser(resolve_entities=False, no_network=True)
    )


def _tracking_enabled(settings: etree._Element) -> bool:
    track = settings.find("w:trackRevisions", WORD_NAMESPACES)
    if track is None:
        return False
    default_tab = settings.find("w:defaultTabStop", WORD_NAMESPACES)
    if default_tab is not None and settings.index(track) > settings.index(default_tab):
        raise ValidationError("trackRevisions follows defaultTabStop, violating settings order")
    return track.get(f"{{{WORD_NS}}}val", "true") in {"true", "1", "on"}


def _check_comments(
    tree: etree._Element,
    comments: etree._Element,
    relations: etree._Element,
    types: etree._Element,
) -> list[etree._Element]:
    """The comments part is reachable, and every comment is anchored around text.

    Returns the comment nodes. A comment whose range does not enclose text before its
    reference opens in Word as a note attached to nothing.
    """
    if not any(
        node.get("Type") == COMMENT_REL
        and node.get("Target") == "comments.xml"
        and node.get("TargetMode", "Internal") == "Internal"
        for node in relations
    ):
        raise ValidationError("no internal relationship to the comments part")
    if not any(
        node.get("PartName") == "/word/comments.xml" and node.get("ContentType") == COMMENT_TYPE
        for node in types
    ):
        raise ValidationError("comments part has no matching content type")
    comment_nodes: list[etree._Element] = comments.findall("w:comment", WORD_NAMESPACES)
    comment_ids = [node.get(f"{{{WORD_NS}}}id") for node in comment_nodes]
    if None in comment_ids or len(set(comment_ids)) != len(comment_ids):
        raise ValidationError("missing or duplicate comment ids")
    nodes = list(tree.iter())
    positions = {}
    for kind in ("commentRangeStart", "commentRangeEnd", "commentReference"):
        found = [
            (index, node.get(f"{{{WORD_NS}}}id"))
            for index, node in enumerate(nodes)
            if node.tag == f"{{{WORD_NS}}}{kind}"
        ]
        if sorted(cid for _, cid in found) != sorted(comment_ids):
            raise ValidationError(f"comment anchors disagree: {kind}")
        positions[kind] = {cid: index for index, cid in found}
    for cid in comment_ids:
        start, end, reference = (
            positions[kind][cid]
            for kind in ("commentRangeStart", "commentRangeEnd", "commentReference")
        )
        if not start < end < reference or not any(
            node.tag == f"{{{WORD_NS}}}t" and node.text for node in nodes[start + 1 : end]
        ):
            raise ValidationError("comment range does not enclose text before its reference")
    if any(not node.xpath(".//w:t/text()", namespaces=WORD_NAMESPACES) for node in comment_nodes):
        raise ValidationError("empty comment")
    return comment_nodes


def _comment_props(data: bytes) -> dict[str, Any]:
    """How many comments there are, and who wrote them."""
    with _archive(data) as archive:
        tree = _word_xml(archive, "word/document.xml")
        comments = _word_xml(archive, "word/comments.xml")
        relations = _word_xml(archive, "word/_rels/document.xml.rels")
        types = _word_xml(archive, "[Content_Types].xml")
    nodes = _check_comments(tree, comments, relations, types)
    authors = {node.get(f"{{{WORD_NS}}}author") for node in nodes}
    if None in authors or "" in authors:
        raise ValidationError("a comment has no author")
    return {"comments": len(nodes), "comment_authors": sorted(authors)}


def _revision_props(data: bytes) -> dict[str, Any]:
    """Read revisions and comment wiring directly, including the accepted text view."""
    with _archive(data) as archive:
        tree = _word_xml(archive, "word/document.xml")
        comments = _word_xml(archive, "word/comments.xml")
        relations = _word_xml(archive, "word/_rels/document.xml.rels")
        types = _word_xml(archive, "[Content_Types].xml")
        settings = _word_xml(archive, "word/settings.xml")
    comment_nodes = _check_comments(tree, comments, relations, types)
    insertions = tree.findall(".//w:ins", WORD_NAMESPACES)
    deletions = tree.findall(".//w:del", WORD_NAMESPACES)
    ids = []
    for revision in (*insertions, *deletions):
        rid = revision.get(f"{{{WORD_NS}}}id")
        if (
            not rid
            or not rid.isdecimal()
            or not revision.get(f"{{{WORD_NS}}}author")
            or not revision.get(f"{{{WORD_NS}}}date")
        ):
            raise ValidationError("revision lacks an id, author or date")
        ids.append(rid)
        deleted = revision.tag == f"{{{WORD_NS}}}del"
        expected, forbidden = ("delText", "t") if deleted else ("t", "delText")
        values = revision.findall(f".//w:{expected}", WORD_NAMESPACES)
        if not any(node.text for node in values) or revision.findall(
            f".//w:{forbidden}", WORD_NAMESPACES
        ):
            raise ValidationError(f"revision must contain {expected}, without {forbidden}")
    if len(set(ids)) != len(ids):
        raise ValidationError("duplicate revision ids")

    current = "\n".join(
        "".join(paragraph.xpath(".//w:t[not(ancestor::w:del)]/text()", namespaces=WORD_NAMESPACES))
        for paragraph in tree.findall(".//w:p", WORD_NAMESPACES)
    )
    return {
        "insertions": len(insertions),
        "deletions": len(deletions),
        "comments": len(comment_nodes),
        "deleted_text": "".join(
            tree.xpath(".//w:del//w:delText/text()", namespaces=WORD_NAMESPACES)
        ),
        "inserted_text": "".join(tree.xpath(".//w:ins//w:t/text()", namespaces=WORD_NAMESPACES)),
        "current_text": current,
        "tracking_enabled": _tracking_enabled(settings),
    }


def _drawing_props(data: bytes) -> dict[str, Any]:
    """Inline and anchored drawings, and how many carry alt text, from document.xml.

    An anchored drawing floats with text wrapped around it. Readers that walk inline shapes
    alone report a document with one as having no picture, so the two are counted apart.
    """
    with _archive(data) as archive:
        body = _word_xml(archive, "word/document.xml")
    described = [
        doc_pr
        for doc_pr in body.iterfind(".//wp:docPr", DRAWING_NAMESPACES)
        if (doc_pr.get("descr") or "").strip()
    ]
    return {
        "inline_images": len(body.findall(".//wp:inline", DRAWING_NAMESPACES)),
        "anchored_images": len(body.findall(".//wp:anchor", DRAWING_NAMESPACES)),
        "images_with_alt_text": len(described),
    }


def _scripts(text: str) -> list[str]:
    """The scripts the letters in `text` belong to, as Unicode names them, sorted.

    Han is how Unicode names the characters Chinese and Japanese share. Emoji, combining
    marks and punctuation are not letters and add nothing.
    """
    found = set()
    for character in text:
        if character.isalpha():
            first = unicodedata.name(character, "UNKNOWN").split(" ", 1)[0].lower()
            found.add("han" if first == "cjk" else first)
    return sorted(found)


def _page_breaks(tree: etree._Element) -> int:
    """Forced page breaks: `w:br w:type="page"` and `w:pageBreakBefore`."""
    explicit = [
        br for br in tree.iter(f"{{{WORD_NS}}}br") if br.get(f"{{{WORD_NS}}}type") == "page"
    ]
    before = [
        flag
        for flag in tree.iter(f"{{{WORD_NS}}}pageBreakBefore")
        if flag.get(f"{{{WORD_NS}}}val", "true") not in FALSE_VALUES
    ]
    return len(explicit) + len(before)


def _header_footer_props(archive: zipfile.ZipFile, tree: etree._Element) -> dict[str, Any]:
    """The header and footer parts a section points at, and what they say.

    A `headerReference` whose relationship or part is missing opens as a document with no
    header and no error, which is how a lost header goes unnoticed.
    """
    references: dict[str, list[str]] = {"header": [], "footer": []}
    for section in tree.iter(f"{{{WORD_NS}}}sectPr"):
        for kind, ids in references.items():
            for reference in section.findall(f"w:{kind}Reference", WORD_NAMESPACES):
                ids.append(reference.get(f"{{{RELATIONSHIP_NS}}}id", ""))
    if not any(references.values()):
        return {}
    targets = {
        node.get("Id"): node.get("Target")
        for node in _word_xml(archive, "word/_rels/document.xml.rels")
    }
    props: dict[str, Any] = {}
    for kind, ids in references.items():
        parts = []
        for rid in dict.fromkeys(ids):
            target = targets.get(rid)
            if target is None or f"word/{target}" not in archive.namelist():
                raise ValidationError(f"a {kind} reference points at no part ({rid!r})")
            parts.append(_word_xml(archive, f"word/{target}"))
        if not parts:
            continue
        props[f"{kind}s"] = len(parts)
        props[f"{kind}_text"] = "".join(parts[0].xpath(".//w:t/text()", namespaces=WORD_NAMESPACES))
        if kind == "footer":
            codes = parts[0].xpath(
                ".//w:fldSimple/@w:instr | .//w:instrText/text()", namespaces=WORD_NAMESPACES
            )
            props["footer_fields"] = sorted(
                {str(code).split()[0] for code in codes if code.strip()}
            )
    return props


def _toc_props(
    document: docx.document.Document, tree: etree._Element, settings: etree._Element
) -> dict[str, Any]:
    """A table-of-contents field, its cached entries and whether they match the headings.

    The entries are what a reader that does not update fields shows, so each one has to
    name the heading it stands for, at the level and on the page it really is on.
    """
    codes = [node.text or "" for node in tree.iter(f"{{{WORD_NS}}}instrText")]
    fields = sum(1 for code in codes if code.strip().startswith("TOC"))
    if not fields:
        return {}
    marks = [mark.get(f"{{{WORD_NS}}}fldCharType") for mark in tree.iter(f"{{{WORD_NS}}}fldChar")]
    if not marks.count("begin") == marks.count("separate") == marks.count("end"):
        raise ValidationError("a field is not closed: begin, separate and end do not pair up")

    headings: list[tuple[int, str]] = []
    pages: list[int] = []
    entries: list[tuple[int, str, str]] = []
    page = 1
    for paragraph in document.paragraphs:
        name = paragraph.style.name if paragraph.style is not None else ""
        if paragraph.paragraph_format.page_break_before:
            page += 1
        if name.startswith("Heading ") and name.split()[1].isdigit():
            headings.append((int(name.split()[1]), paragraph.text))
            pages.append(page)
        elif name in {"toc 1", "toc 2"}:
            title, _, shown = paragraph.text.rpartition("\t")
            entries.append((int(name[-1]), title, shown))
    if [(level, title) for level, title, _ in entries] != headings:
        raise ValidationError(
            f"the contents entries {[t for _, t, _ in entries]} do not match the headings "
            f"{[t for _, t in headings]}"
        )
    for (_, title, shown), real in zip(entries, pages, strict=True):
        if shown != str(real):
            raise ValidationError(f"the contents say {title!r} is on page {shown}, not {real}")

    update = settings.find("w:updateFields", WORD_NAMESPACES)
    if update is not None:
        after = [settings.find(f"w:{name}", WORD_NAMESPACES) for name in UPDATE_FIELDS_SUCCESSORS]
        position = settings.index(update)
        if any(node is not None and settings.index(node) < position for node in after):
            raise ValidationError("updateFields follows a later settings element, out of order")
    on = update is not None and update.get(f"{{{WORD_NS}}}val", "true") not in FALSE_VALUES
    return {
        "headings": len(headings),
        "toc_fields": fields,
        "toc_entries": len(entries),
        "update_fields_on_open": on,
    }


def _layout_props(data: bytes, document: docx.document.Document, text: str) -> dict[str, Any]:
    """Page breaks, headers and footers, a table of contents and scripts: each reported only
    for a document that has it, so no entry published before them changes."""
    with _archive(data) as archive:
        tree = _word_xml(archive, "word/document.xml")
        settings = _word_xml(archive, "word/settings.xml")
        props = _header_footer_props(archive, tree)
    breaks = _page_breaks(tree)
    if breaks:
        # .docx stores no page count; each forced break guarantees one more page.
        props = {"page_breaks": breaks, "min_pages": breaks + 1, **props}
    props.update(_toc_props(document, tree, settings))
    scripts = _scripts(text)
    if len(scripts) > 1:
        props["scripts"] = scripts
    rtl = len(tree.findall(".//w:pPr/w:bidi", WORD_NAMESPACES))
    if rtl:
        props["rtl_paragraphs"] = rtl
    return props


def _archive(data: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"not a readable zip container: {exc}") from exc


def _check_package(data: bytes, required: tuple[str, ...]) -> list[str]:
    """The zip-level reading: the parts an OOXML consumer looks for before parsing."""
    with _archive(data) as archive:
        names = archive.namelist()
        broken = archive.testzip()
        if broken is not None:
            raise ValidationError(f"corrupt entry in the package: {broken}")
    missing = [name for name in (*OOXML_REQUIRED, *required) if name not in names]
    if missing:
        raise ValidationError(f"package is missing required parts: {missing}")
    return names


@register("docx")
def validate_docx(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    names = _check_package(data, ("word/document.xml",))
    try:
        document = docx.Document(io.BytesIO(data))
        paragraphs = [p for p in document.paragraphs if p.text.strip()]
        tables = document.tables
        table_rows = [len(table.rows) for table in tables]
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"python-docx could not read it: {exc}") from exc

    images = [name for name in names if name.startswith("word/media/")]
    if fixture.params.get("images") and not images:
        raise ValidationError("declares images but the package has no word/media parts")
    for index, rows in enumerate(table_rows):
        if rows < MIN_TABLE_ROWS:
            raise ValidationError(f"table {index} has {rows} row(s): no header plus data")
    revisions = _revision_props(data) if fixture.generator == "office.docx_tracked_changes" else {}
    comments = _comment_props(data) if fixture.generator == "office.docx_comments" else {}
    text = "\n".join(p.text for p in document.paragraphs)
    text += "\n".join(cell.text for table in tables for row in table.rows for cell in row.cells)
    return {
        "paragraphs": len(paragraphs),
        "tables": len(tables),
        "table_rows": table_rows[0] if table_rows else 0,
        "images": len(images),
        "words": sum(len(p.text.split()) for p in paragraphs),
        **_drawing_props(data),
        **revisions,
        **comments,
        **_layout_props(data, document, text),
    }


CHART_NAMESPACES = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
#: A chart's reference to cells: `Signups!$B$2:$B$5` or `'Order lines'!$B$2:$B$5`.
CHART_REFERENCE = re.compile(r"^(?:'((?:[^']|'')+)'|([^'!]+))!(.+)$")


def _check_chart_reference(workbook: Any, reference: str) -> None:  # noqa: ANN401 - openpyxl is untyped
    """A chart that reads a sheet that is not there, or cells with nothing in them, opens
    without complaint and draws nothing."""
    match = CHART_REFERENCE.match(reference)
    if match is None:
        raise ValidationError(f"chart reference {reference!r} is not a sheet and a range")
    title = (match.group(1) or match.group(2)).replace("''", "'")
    if title not in workbook.sheetnames:
        raise ValidationError(f"a chart reads sheet {title!r}, which the workbook does not have")
    min_col, min_row, max_col, max_row = range_boundaries(match.group(3).replace("$", ""))
    cells = workbook[title].iter_rows(
        min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col, values_only=True
    )
    if all(value is None for row in cells for value in row):
        raise ValidationError(f"a chart reads {reference}, which holds nothing")


def _chart_props(
    archive: zipfile.ZipFile,
    names: list[str],
    workbook: Any,  # noqa: ANN401 - openpyxl is untyped
) -> dict[str, Any]:
    """Charts, their series and kinds, each series held to cells that exist and hold values."""
    parts = sorted(name for name in names if re.fullmatch(r"xl/charts/chart\d+\.xml", name))
    if not parts:
        return {}
    series = 0
    kinds: set[str] = set()
    for part in parts:
        root = _word_xml(archive, part)
        plot = root.find(".//c:plotArea", CHART_NAMESPACES)
        if plot is None:
            raise ValidationError(f"{part} has no plot area")
        kinds.update(
            etree.QName(node).localname.removesuffix("Chart")
            for node in plot
            if etree.QName(node).localname.endswith("Chart")
        )
        for one in root.iterfind(".//c:ser", CHART_NAMESPACES):
            series += 1
            references = [node.text or "" for node in one.iterfind(".//c:f", CHART_NAMESPACES)]
            if not references:
                raise ValidationError(f"a series in {part} reads no cells")
            for reference in references:
                _check_chart_reference(workbook, reference)
    return {"charts": len(parts), "chart_series": series, "chart_types": sorted(kinds)}


@register("xlsx")
def validate_xlsx(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    names = _check_package(data, ("xl/workbook.xml",))
    try:
        workbook = load_workbook(io.BytesIO(data))
        cached = load_workbook(io.BytesIO(data), data_only=True)
    except Exception as exc:
        raise ValidationError(f"openpyxl could not read it: {exc}") from exc

    sheet = workbook.worksheets[0]
    formulas = [
        (worksheet.title, cell)
        for worksheet in workbook.worksheets
        for row in worksheet.iter_rows()
        for cell in row
        if isinstance(cell.value, str) and cell.value.startswith("=")
    ]
    # The whole point of caching values: a reader that does not calculate must still
    # see numbers. openpyxl writes an empty <v/> placeholder, which reads back as
    # None — so an uncached formula fixture is useless without ever failing to parse.
    empty = [
        f"{title}!{cell.coordinate}"
        for title, cell in formulas
        if cached[title][cell.coordinate].value is None
    ]
    if empty:
        raise ValidationError(f"formula cells carry no cached value: {sorted(empty)[:5]}")

    rows = sheet.max_row
    if rows < 1:
        raise ValidationError("the first worksheet has no rows")
    props: dict[str, Any] = {
        "sheets": len(workbook.worksheets),
        "sheet_names": ",".join(workbook.sheetnames),
        "rows": rows,
        "columns": sheet.max_column,
        "formulas": len(formulas),
        "images": sum(len(worksheet._images) for worksheet in workbook.worksheets),
    }
    # Reported only when present, so the workbooks published before it keep their props.
    across = sum(1 for _, cell in formulas if "!" in cell.value)
    if across:
        props["cross_sheet_formulas"] = across
    merged = sorted(str(merged_range) for merged_range in sheet.merged_cells.ranges)
    if merged:
        props["merged_ranges"] = len(merged)
        props["merged"] = merged
    if sheet.auto_filter.ref:
        # The header is frozen so it stays in view while the filter works on the rows below.
        props["auto_filter"] = sheet.auto_filter.ref
        props["freeze_panes"] = sheet.freeze_panes
    with _archive(data) as archive:
        props.update(_chart_props(archive, names, workbook))
    if fixture.generator == "office.xlsx_unicode":
        strings = [
            cell.value for row in sheet.iter_rows() for cell in row if isinstance(cell.value, str)
        ]
        props["scripts"] = _scripts("\n".join(strings))
        props["rtl_cells"] = sum(
            1
            for row in sheet.iter_rows()
            for cell in row
            if cell.alignment.readingOrder == RIGHT_TO_LEFT
        )
    return props


@register("pptx")
def validate_pptx(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
    names = _check_package(data, ("ppt/presentation.xml",))
    try:
        presentation = Presentation(io.BytesIO(data))
        slides = list(presentation.slides)
    except Exception as exc:
        raise ValidationError(f"python-pptx could not read it: {exc}") from exc

    if not slides:
        raise ValidationError("has no slides")
    layouts = {slide.slide_layout.name for slide in slides}
    return {
        "slides": len(slides),
        "layouts": len(layouts),
        "images": len([name for name in names if name.startswith("ppt/media/")]),
        "slide_width_emu": presentation.slide_width,
        "slide_height_emu": presentation.slide_height,
        "notes": sum(1 for slide in slides if slide.has_notes_slide),
        "tables": sum(1 for slide in slides for shape in slide.shapes if shape.has_table),
        "charts": sum(1 for slide in slides for shape in slide.shapes if shape.has_chart),
        "hidden_slides": sum(1 for slide in slides if slide._element.get("show") == "0"),
    }


@register("rtf")
def validate_rtf(data: bytes, _fixture: Fixture, mime: str) -> dict[str, Any]:
    """RTF has no library reader in the toolchain, so the structure is checked directly.

    Brace balance is the check that matters: an unbalanced RTF opens as an empty document
    in some readers and as garbage in others, and neither reports an error.
    """
    if not data.startswith(b"{\\rtf1"):
        raise ValidationError("does not start with the RTF signature {\\rtf1")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"contains non-ASCII bytes at {exc.start}") from exc

    depth = 0
    for index, character in enumerate(text):
        if index and text[index - 1] == "\\":
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                raise ValidationError(f"closing brace with no opening one at byte {index}")
    if depth != 0:
        raise ValidationError(f"{depth} unclosed group(s)")
    return {
        # `\par` is a prefix of `\pard`, so a plain count double-counts every paragraph
        # that opens with a paragraph-default reset. RTF control words end at the first
        # non-letter, which is what the lookahead encodes.
        **text_props(data, mime),
        "paragraphs": len(re.findall(r"\\par(?![a-zA-Z])", text)),
        "has_font_table": r"\fonttbl" in text,
        **_rtf_structure(text),
    }


def _rtf_structure(text: str) -> dict[str, Any]:
    """Tables, colours and character formatting, each reported only where there is any.

    A row whose cells do not match its cell edges, a colour the table does not hold and a
    font that was never declared are all things a reader renders differently or not at all,
    with no error.
    """
    header, _, body = text.partition("\\pard")
    props: dict[str, Any] = {}
    starts = len(re.findall(r"\\trowd(?![a-zA-Z])", text))
    ends = len(re.findall(r"\\row(?![a-zA-Z])", text))
    if starts != ends:
        raise ValidationError(f"{starts} table row(s) opened and {ends} closed")
    if starts:
        widths = set()
        for row in re.findall(r"\\trowd(?![a-zA-Z])(.*?)\\row(?![a-zA-Z])", text, re.DOTALL):
            edges = len(re.findall(r"\\cellx\d+", row))
            cells = len(re.findall(r"\\cell(?![a-zA-Z])", row))
            if edges != cells:
                raise ValidationError(f"a table row has {edges} cell edge(s) and {cells} cell(s)")
            widths.add(edges)
        if len(widths) != 1:
            raise ValidationError(f"table rows differ in width: {sorted(widths)}")
        props["table_rows"] = starts
        props["table_columns"] = widths.pop()
    colours = re.search(r"\{\\colortbl([^}]*)\}", header)
    used = [int(number) for number in re.findall(r"\\cf(\d+)(?![0-9a-zA-Z])", body)]
    if colours:
        props["has_color_table"] = True
        known = colours.group(1).count(";")
        if used and max(used) >= known:
            raise ValidationError(f"\\cf{max(used)} names a colour the table does not have")
    elif used:
        raise ValidationError("text is coloured but there is no colour table")
    declared = set(re.findall(r"\{\\f(\d+)\\", header))
    undeclared = set(re.findall(r"\\f(\d+)(?![0-9a-zA-Z])", body)) - declared
    if undeclared:
        raise ValidationError(f"text uses font(s) {sorted(undeclared)} that the font table lacks")
    for name, word in (("bold", "b"), ("italic", "i"), ("underline", "ul")):
        spans = len(re.findall(rf"\\{word}(?![a-zA-Z0-9])", body))
        if spans:
            props[f"{name}_spans"] = spans
    if used:
        props["colored_spans"] = len(used)
    return props


OPF_NAMESPACES = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
}
NCX_TYPE = "application/x-dtbncx+xml"
XHTML_TYPE = "application/xhtml+xml"
IMG_TAG = re.compile(r"<img\b([^>]*)>", re.IGNORECASE)


def _resolved(base: str, href: str) -> str:
    """`href` as a path in the zip, relative to the part `base` that names it."""
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), href.partition("#")[0]))


def _epub_package(
    archive: zipfile.ZipFile, opf: str
) -> tuple[etree._Element, dict[str, tuple[str, str]]]:
    """The package document and its manifest as {id: (path in the zip, media type)}.

    Every item must be in the archive: a reader that finds a manifest entry with no file
    behind it stops, or skips the rest of the book, depending on the reader.
    """
    package = _word_xml(archive, opf)
    manifest: dict[str, tuple[str, str]] = {}
    for item in package.iterfind("opf:manifest/opf:item", OPF_NAMESPACES):
        path = _resolved(opf, item.get("href", ""))
        if path not in archive.namelist():
            raise ValidationError(
                f"manifest item {item.get('id')!r} names {path}, which is not in the book"
            )
        manifest[item.get("id", "")] = (path, item.get("media-type", ""))
    for reference in package.iterfind("opf:spine/opf:itemref", OPF_NAMESPACES):
        if reference.get("idref") not in manifest:
            raise ValidationError(
                f"the spine names {reference.get('idref')!r}, which is not in the manifest"
            )
    return package, manifest


def _epub2_navigation(
    archive: zipfile.ZipFile, package: etree._Element, manifest: dict[str, tuple[str, str]]
) -> None:
    """EPUB 2's table of contents: the spine's `toc` is an NCX whose uid is the book's id."""
    spine = package.find("opf:spine", OPF_NAMESPACES)
    ncx_id = spine.get("toc") if spine is not None else None
    if ncx_id is None or ncx_id not in manifest or manifest[ncx_id][1] != NCX_TYPE:
        raise ValidationError("the spine's toc does not name an NCX item in the manifest")
    ncx_path = manifest[ncx_id][0]
    ncx = _word_xml(archive, ncx_path)
    identifier = package.findtext("opf:metadata/dc:identifier", namespaces=OPF_NAMESPACES)
    uid = next(
        (
            node.get("content")
            for node in ncx.iterfind("ncx:head/ncx:meta", OPF_NAMESPACES)
            if node.get("name") == "dtb:uid"
        ),
        None,
    )
    if uid != identifier:
        raise ValidationError(f"the NCX uid {uid!r} is not the book's identifier {identifier!r}")
    known = {path for path, _ in manifest.values()}
    points = ncx.findall(".//ncx:navPoint", OPF_NAMESPACES)
    if not points:
        raise ValidationError("the NCX has no navPoint")
    for point in points:
        content = point.find("ncx:content", OPF_NAMESPACES)
        target = _resolved(ncx_path, content.get("src", "") if content is not None else "")
        if target not in known:
            raise ValidationError(f"a navPoint points at {target}, which is not in the manifest")


def _epub_images(archive: zipfile.ZipFile, manifest: dict[str, tuple[str, str]]) -> int:
    """Image items, and every `<img>` in the book resolving to one of them with alt text."""
    images = {path for path, media in manifest.values() if media.startswith("image/")}
    for path, media in manifest.values():
        if media != XHTML_TYPE:
            continue
        for attributes in IMG_TAG.findall(archive.read(path).decode("utf-8")):
            source = re.search(r'\bsrc="([^"]*)"', attributes)
            target = _resolved(path, source.group(1) if source else "")
            if target not in images:
                raise ValidationError(
                    f"{path} shows {target}, which is not an image in the manifest"
                )
            if not re.search(r'\balt="[^"]+"', attributes):
                raise ValidationError(f"{path} shows {target} with no alt text")
    return len(images)


def _epub_container(archive: zipfile.ZipFile) -> str:
    """OCF's three rules for the container, and the package document it points at."""
    names = archive.namelist()
    if names[0] != "mimetype":
        raise ValidationError(f"first entry is '{names[0]}', not 'mimetype' (OCF 3.0 §4.1)")
    if archive.infolist()[0].compress_type != zipfile.ZIP_STORED:
        raise ValidationError("the mimetype entry is compressed; OCF requires it stored")
    if archive.read("mimetype") != EPUB_MIMETYPE:
        raise ValidationError("the mimetype entry does not hold application/epub+zip")
    if "META-INF/container.xml" not in names:
        raise ValidationError("no META-INF/container.xml")
    opf = [name for name in names if name.endswith(".opf")]
    if not opf:
        raise ValidationError("no package document (.opf) in the container")
    if opf[0] not in archive.read("META-INF/container.xml").decode("utf-8"):
        raise ValidationError(f"container.xml does not point at the package document {opf[0]}")
    return opf[0]


@register("epub")
def validate_epub(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
    """EPUB is a zip with rules the zip format itself will not enforce.

    Both versions are read: 3.0 has a nav document and a modification date, 2.0 has an NCX
    that the spine names and no nav document.
    """
    with _archive(data) as archive:
        opf = _epub_container(archive)
        text = archive.read(opf).decode("utf-8")
        chapters = [name for name in archive.namelist() if name.endswith(".xhtml")]
        version = "3.0" if 'version="3.0"' in text else "2.0"
        required = ["<dc:identifier", "<dc:title", "<dc:language"]
        for element in [*required, *(["dcterms:modified"] if version == "3.0" else [])]:
            if element not in text:
                raise ValidationError(f"the package document has no {element}")
        package, manifest = _epub_package(archive, opf)
        has_nav = 'properties="nav"' in text
        if version == "3.0" and not has_nav:
            raise ValidationError("the package document declares no nav document (EPUB 3 §5.2)")
        if version == "2.0":
            if has_nav:
                raise ValidationError("an EPUB 2 package declares a nav document, which is 3's")
            _epub2_navigation(archive, package, manifest)
        props: dict[str, Any] = {
            "chapters": len([name for name in chapters if "chapter" in name]),
            "documents": len(chapters),
            "epub_version": version,
            "has_nav": has_nav,
            **({"has_ncx": True} if version == "2.0" else {}),
        }
        images = _epub_images(archive, manifest)
    return {**props, **({"images": images} if images else {})}
