"""Validator for the edge cases (docs/06 §6, docs/05 §3.13).

Every other validator asks "is this a good file of its format?". This one asks the
opposite: the catalog declares a defect, and the fixture has to *have* that defect. A
truncated PDF that somehow parses, or a zero-byte file with bytes in it, is a broken
fixture even though nothing crashed — so each defect is asserted directly, and the
intended format's own validator is the negative control where that is the test.

Four of the published props describe the breakage rather than the format, and none of
them is written by hand (docs/04 §1.3.1):

``derived_from``
    the fixture this one was cut or copied from, asserted byte for byte against it.
``compare_with``
    the valid file of the same announced type, from the catalog and cross-checked there.
``damage``
    one sentence, composed here out of what was measured — where the file stops, which
    structure is missing, where a parser gives up.
``outcome``
    ``must-fail``, ``may-recover`` or ``varies``, derived from two readings of the bytes
    and required to equal the value the catalog declares.

The outcome derivation is the definition of the three words. The bytes are offered to
the reader for the type the file announces, and to a **conforming** tolerant reading —
one the format actually permits, not any tool that might scrape something out. Whether
that gets the content whole, in part, or not at all is the outcome. It is a property of
the file: "a reader may recover this" never says a reader must.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any

from lxml import etree

from loremfile.catalog import Defect, Edge, Fixture, Outcome
from loremfile.validators import MAGIC, ValidationError, has_validator, register, validator_for

#: The end of a PNG IHDR chunk: signature (8) + length and type (8) + width and height.
IHDR_END = 24

#: What a reader substitutes for an ill-formed byte sequence (Unicode 16.0 §3.9).
REPLACEMENT = "\ufffd"

#: A byte-order mark for each encoding an edge fixture may carry.
BOMS = (b"\xef\xbb\xbf", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff", b"\xff\xfe", b"\xfe\xff")


def read_source(path: str) -> bytes:
    """The bytes of the fixture a derived edge case was cut or copied from.

    The build generates every dependency before its dependent and writes both into
    ``build/fixtures/``, so the source is on disk beside the file under validation.
    Nothing is regenerated here: a truncation has to be a prefix of the bytes that were
    actually published, and rebuilding could differ from them.
    """
    from loremfile import build  # noqa: PLC0415 - deferred so validators stay importable

    target = build.fixtures_dir() / path
    if not target.is_file():
        raise ValidationError(
            f"cannot be checked against {path}: that file is not in build/fixtures. "
            "Build it together with this one — `build --only` pulls dependencies in"
        )
    return target.read_bytes()


#: How the source is read. A seam for the tests, which check the byte arithmetic
#: against sources they construct rather than against a repository-wide build.
SOURCE_READER: Callable[[str], bytes] = read_source


@dataclass(frozen=True)
class Subject:
    """The bytes under validation, and everything a check reads about them."""

    data: bytes
    fixture: Fixture
    edge: Edge
    mime: str

    @property
    def claimed_format(self) -> str:
        """The format the file announces — its extension, which is also its media type.

        Not the same as ``edge.intended_format`` for a mislabelled file: the bytes of
        ``png-with-pdf-extension.pdf`` are png, and what it announces is pdf.
        """
        return self.fixture.ext

    @property
    def source_path(self) -> str:
        path = self.edge.source_fixture
        if path is None:  # pragma: no cover - the caller checks the defect first
            raise ValidationError("declares no source_fixture to be checked against")
        return path

    def source(self) -> bytes:
        return SOURCE_READER(self.source_path)

    def accepts(self, fmt: str) -> bool:
        """Whether the registered reader for ``fmt`` accepts these bytes.

        A format with no reader registered cannot answer the question, and a "no" from
        a reader that was never run is the shape of check that passes on absence — so
        the caller is told to stop rather than given a False.
        """
        if not has_validator(fmt):
            raise ValidationError(
                f"needs the {fmt} validator to say what a reader does with it, "
                "and no validator is registered for that format"
            )
        try:
            validator_for(fmt)(self.data, self.fixture, self.mime)
        except Exception:  # any reader refusing these bytes is an answer, not an error
            return False
        return True


# --- what a conforming reader can still get out of the bytes ------------------------------


@dataclass(frozen=True)
class Recovery:
    """What survives in a broken file, and whether that is all of it.

    ``whole`` is the line between ``varies`` and ``may-recover``: a file that some
    conforming reader reads entire is not damaged content, it is a file readers
    disagree about.
    """

    whole: bool
    evidence: str


#: One tolerant reading per announced format, tried when the strict reader refuses.
#: Each is a reading the format itself permits — not "some tool can scrape this".
RECOVERIES: dict[str, Callable[[bytes], Recovery | None]] = {}


def _recovers(fmt: str) -> Callable[[Callable[[bytes], Recovery | None]], Callable[..., Any]]:
    def decorate(func: Callable[[bytes], Recovery | None]) -> Callable[..., Any]:
        RECOVERIES[fmt] = func
        return func

    return decorate


@_recovers("pdf")
def _recover_pdf(data: bytes) -> Recovery | None:
    """Rebuilding a lost cross-reference table by scanning for objects is what a PDF
    reader does with a damaged file (PDF 2.0 §7.5.4 makes the table the index, not the
    content), so the objects that arrived are recoverable without it."""
    if not data.startswith(b"%PDF-"):
        return None
    objects = data.count(b"endobj")
    if not objects:
        return None
    version = data[5:8].decode("ascii", "replace")
    return Recovery(
        whole=False,
        evidence=(
            f"the %PDF-{version} header and {objects} complete objects, which a reader "
            "that rebuilds the cross-reference table by scanning can still use"
        ),
    )


@_recovers("png")
def _recover_png(data: bytes) -> Recovery | None:
    """IHDR is the first chunk and carries the dimensions; a decoder that has it can
    lay out the image before any pixel arrives."""
    if not data.startswith(MAGIC["png"][0]) or data[12:16] != b"IHDR" or len(data) < IHDR_END:
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return Recovery(
        whole=False, evidence=f"the signature and an IHDR chunk giving {width}x{height}"
    )


@_recovers("jpg")
def _recover_jpg(data: bytes) -> Recovery | None:
    """A JPEG decoder paints the scan lines that arrived — the way a browser shows an
    image while it loads — so a cut file still yields its header and the rows above the
    cut."""
    from PIL import Image  # noqa: PLC0415 - a heavy import the other branches never need

    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size
    except Exception:
        return None
    try:
        image.load()
    except Exception:
        return Recovery(
            whole=False,
            evidence=(
                f"the {width}x{height} header and the scan lines that arrived, the way a "
                "browser paints an image that is still loading"
            ),
        )
    return Recovery(whole=True, evidence=f"the whole {width}x{height} image")


@_recovers("zip")
def _recover_zip(data: bytes) -> Recovery | None:
    """Each entry is preceded by its own local file header, which is why a streaming
    extractor (APPNOTE §4.3.6) reads an archive front to back without ever seeing the
    central directory."""
    names = _local_entry_names(data)
    if not names:
        return None
    return Recovery(
        whole=False,
        evidence=(
            f"{len(names)} entries still named by local file headers "
            f"({', '.join(names)}), which a streaming extractor reads front to back"
        ),
    )


@_recovers("mp4")
def _recover_mp4(data: bytes) -> Recovery | None:
    """Every box carries its own size and type, so the boxes that arrived whole are
    readable however the file ends."""
    if data[4:8] != b"ftyp":
        return None
    boxes = [box for box, _offset, _size in _walk_boxes(data)[0]]
    return Recovery(
        whole=False,
        evidence=f"the boxes that arrived whole ({', '.join(boxes)}) and the streams they describe",
    )


@_recovers("json")
def _recover_json(data: bytes) -> Recovery | None:
    """RFC 8259 §8.1 lets a parser ignore a byte-order mark at the start of a JSON text.
    Nothing else in JSON is optional, so that is the whole of the tolerance: a trailing
    comma or a missing value has no conforming reading at all."""
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return Recovery(
        whole=True,
        evidence=(
            f"the whole document (a JSON {_json_kind(document)}) once the byte-order mark "
            "is skipped"
        ),
    )


#: JSON's names for the things a parser returns; Python's differ, and the props are read
#: by people who are looking at JSON.
JSON_KINDS = {dict: "object", list: "array", str: "string", bool: "boolean", type(None): "null"}


def _json_kind(document: object) -> str:
    return JSON_KINDS.get(type(document), "number")


@_recovers("csv")
def _recover_csv(data: bytes) -> Recovery | None:
    """RFC 4180 §2 requires at least one record and says every record "should" contain
    the same number of fields — a recommendation with no error handling attached, which
    is why readers return ragged rows rather than refusing them."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    rows = [row for row in csv.reader(io.StringIO(text)) if row]
    if not rows:
        return None
    widths = ", ".join(str(len(row)) for row in rows)
    return Recovery(whole=True, evidence=f"all {len(rows)} rows, of {widths} fields")


def _xml_parser() -> etree.XMLParser:
    """The parser validators/data.py uses: no entity resolution, no network, no DTD."""
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


@_recovers("xml")
def _recover_xml(data: bytes) -> Recovery | None:
    """XML 1.0 §1.2 makes a well-formedness violation a *fatal* error: the processor
    "must not continue normal processing". So there is no tolerant reading to offer —
    either the document parses or a conforming reader returns nothing at all."""
    try:
        root = etree.fromstring(data, parser=_xml_parser())
    except (etree.XMLSyntaxError, ValueError):
        return None
    return Recovery(
        whole=True, evidence=f"the whole document, rooted at <{etree.QName(root).localname}>"
    )


@_recovers("txt")
def _recover_txt(data: bytes) -> Recovery | None:
    """Unicode 16.0 §3.9 (U+FFFD Substitution of Maximal Subparts) defines what a reader
    does with ill-formed bytes: replace and carry on. The text either side survives; the
    replaced bytes do not."""
    text = data.decode("utf-8", errors="replace")
    if not text:
        return None
    replaced = text.count(REPLACEMENT)
    if not replaced:
        return Recovery(whole=True, evidence=f"all {len(text):,} characters")
    return Recovery(
        whole=False,
        evidence=(
            f"{len(text) - replaced:,} of {len(text):,} characters, with {replaced} ill-formed "
            "bytes replaced by U+FFFD as Unicode requires"
        ),
    )


def _tolerant_reading(subject: Subject) -> Recovery | None:
    """What the reading the format itself permits gets out of these bytes."""
    reader = RECOVERIES.get(subject.claimed_format)
    if reader is None:
        raise ValidationError(
            f"has no tolerant reading defined for {subject.claimed_format}, so its outcome "
            "cannot be checked (validators/edge.py RECOVERIES)"
        )
    return reader(subject.data)


def _recovery(subject: Subject) -> Recovery | None:
    """The best reading any conforming reader gets of these bytes.

    The order of the branches is the substance. Asking the format's own reader first
    looks right and is wrong for a file with bytes missing: ffprobe reads a truncated
    MP4 without complaint — the header is intact and the streams are described, which
    is why `_walk_boxes` exists at all — and that answer would make a damaged file
    `varies`. Truncation is settled before any reader is asked.
    """
    if subject.edge.defect is Defect.TRUNCATED:
        # Bytes are missing. Whatever a reader makes of what arrived, it is not the
        # whole file, so this can never be the reading that means `varies`.
        recovery = _tolerant_reading(subject)
        if recovery is None:
            return None
        return Recovery(whole=False, evidence=recovery.evidence)
    if subject.edge.defect is Defect.MISMATCHED_EXTENSION:
        # The name is the only thing wrong: a reader that identifies by content rather
        # than by extension or Content-Type gets the file entire.
        intended = subject.edge.intended_format
        if not subject.accepts(intended):
            return None
        return Recovery(
            whole=True,
            evidence=(
                f"the whole file, as the {intended} it really is, by any reader that "
                "identifies content by its bytes rather than by its name"
            ),
        )
    if subject.accepts(subject.claimed_format):
        return Recovery(
            whole=True,
            evidence=(
                f"the whole file: the {subject.claimed_format} reader it announces itself to "
                "takes these bytes as they are"
            ),
        )
    return _tolerant_reading(subject)


def derive_outcome(subject: Subject) -> tuple[Outcome, str]:
    """What this file does to a reader, and the reading that showed it."""
    recovery = _recovery(subject)
    if recovery is None:
        return Outcome.MUST_FAIL, "no conforming reader gets anything out of it"
    if recovery.whole:
        return Outcome.VARIES, f"a conforming reader gets {recovery.evidence}"
    return Outcome.MAY_RECOVER, f"a conforming reader gets {recovery.evidence}"


# --- reading the containers -----------------------------------------------------------------

#: An ISO-BMFF box header: a four-byte size followed by a four-byte type.
BOX_HEADER_BYTES = 8


def _walk_boxes(data: bytes) -> tuple[list[tuple[str, int, int]], tuple[str, int, int] | None]:
    """Top-level ISO-BMFF boxes: the ones that arrived whole, and the one the file ends
    inside — declaring more bytes than remain — if there is one.

    Both answers come from the same walk because they are the same walk. ffprobe reads a
    truncated MP4 without complaint — the header is intact and the streams are described
    — so "its own validator rejects it" does not detect truncation for this container.
    The box table does.
    """
    whole: list[tuple[str, int, int]] = []
    offset = 0
    while offset + BOX_HEADER_BYTES <= len(data):
        size = int.from_bytes(data[offset : offset + 4], "big")
        box = data[offset + 4 : offset + 8].decode("ascii", "replace")
        if size == 1:  # the real, 64-bit size follows the box type
            if offset + 16 > len(data):
                return whole, (box, offset, len(data) - offset)
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
        elif size == 0:  # runs to the end of the file by definition, so never short
            whole.append((box, offset, len(data) - offset))
            return whole, None
        if size < BOX_HEADER_BYTES:  # not a box table this understands
            return whole, None
        if offset + size > len(data):
            return whole, (box, offset, size)
        whole.append((box, offset, size))
        offset += size
    return whole, None


def _overrunning_box(data: bytes) -> tuple[str, int, int] | None:
    """The box an ISO-BMFF file ends inside. Only files carrying an `ftyp` box qualify."""
    if data[4:8] != b"ftyp":
        return None
    return _walk_boxes(data)[1]


def _local_entry_names(data: bytes) -> list[str]:
    """Entry names read from local file headers alone, ignoring the central directory."""
    names: list[str] = []
    offset = data.find(b"PK\x03\x04")
    while offset != -1 and offset + 30 <= len(data):
        name_length = int.from_bytes(data[offset + 26 : offset + 28], "little")
        name = data[offset + 30 : offset + 30 + name_length]
        if len(name) < name_length:
            break
        names.append(name.decode("utf-8", errors="replace"))
        offset = data.find(b"PK\x03\x04", offset + 1)
    return names


def _archive_names(data: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return archive.namelist()
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"is not a readable archive: {exc}") from exc


def _escaping(names: list[str]) -> list[str]:
    return [name for name in names if name.startswith(("/", "../")) or "/../" in name]


def _decode_errors(data: bytes) -> list[tuple[int, bytes, str]]:
    """Every place the bytes are not UTF-8: offset, the bytes, and the codec's reason."""
    found: list[tuple[int, bytes, str]] = []
    offset = 0
    while offset <= len(data):
        try:
            data[offset:].decode("utf-8")
        except UnicodeDecodeError as exc:
            found.append(
                (offset + exc.start, data[offset + exc.start : offset + exc.end], exc.reason)
            )
            offset += exc.end
        else:
            break
    return found


def _and(parts: Iterable[str]) -> str:
    """``a``, ``a and b``, ``a, b and c`` — these sentences are read by people."""
    items = list(parts)
    if not items[1:]:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


# --- the damage, in one measured sentence -----------------------------------------------------

#: The first structure a reader of each format looks for. Named in the sentence a
#: zero-byte fixture gets, because "it is empty" says nothing about what broke.
FIRST_STRUCTURE = {
    "pdf": "no %PDF- header, and nothing after it to read",
    "png": "no eight-byte PNG signature, so nothing identifies it as an image",
    "jpg": "no SOI marker, so nothing identifies it as an image",
    "zip": "no local file header and no end-of-central-directory record",
    "mp4": "no ftyp box, so nothing declares what the container is",
    "json": "no JSON value, and RFC 8259 requires one",
    "csv": "no header row and no record, and RFC 4180 requires at least one",
    "xml": "no root element, which XML 1.0 requires",
    "txt": "no text to read",
}

#: What truncation takes off the end of each format, and the check that it is gone.
#: A phrase that could be written without looking is the phrase that goes stale.
Missing = Callable[[bytes], str]
MISSING_TAIL: dict[str, Missing] = {}


def _tail(fmt: str) -> Callable[[Missing], Missing]:
    def decorate(func: Missing) -> Missing:
        MISSING_TAIL[fmt] = func
        return func

    return decorate


@_tail("pdf")
def _pdf_tail(data: bytes) -> str:
    if b"startxref" in data or b"%%EOF" in data:
        raise ValidationError("still carries its startxref or %%EOF, so its tail is intact")
    return "the cross-reference table, the trailer and the %%EOF marker are all past the end"


@_tail("jpg")
def _jpg_tail(data: bytes) -> str:
    if data.endswith(b"\xff\xd9"):
        raise ValidationError("ends with the FFD9 end-of-image marker, so the scan is complete")
    return "the scan stops mid-row and the FFD9 end-of-image marker never arrives"


@_tail("zip")
def _zip_tail(data: bytes) -> str:
    if b"PK\x05\x06" in data:
        raise ValidationError("still holds an end-of-central-directory record")
    entries = len(_local_entry_names(data))
    return (
        f"{entries} local file headers survive, and the central directory that lists them "
        "is past the end"
    )


@_tail("mp4")
def _mp4_tail(data: bytes) -> str:
    overrun = _overrunning_box(data)
    if overrun is None:
        raise ValidationError("holds no box that runs past the end, so it is not cut short")
    box, offset, size = overrun
    return (
        f"it ends inside the '{box}' box at offset {offset:,}, which declares {size:,} bytes "
        f"and has {len(data) - offset:,}"
    )


#: One sentence writer per defect. Every value it states is measured here.
Damage = Callable[["Subject"], str]
DAMAGE: dict[Defect, Damage] = {}


def _damage(defect: Defect) -> Callable[[Damage], Damage]:
    def decorate(func: Damage) -> Damage:
        DAMAGE[defect] = func
        return func

    return decorate


@_damage(Defect.ZERO_BYTE)
def _damage_zero_byte(subject: Subject) -> str:
    structure = FIRST_STRUCTURE.get(subject.claimed_format)
    if structure is None:
        raise ValidationError(
            f"is empty, and nothing here says what a {subject.claimed_format} reader "
            "looks for first (validators/edge.py FIRST_STRUCTURE)"
        )
    return f"The file holds no bytes at all: {structure}."


@_damage(Defect.TRUNCATED)
def _damage_truncated(subject: Subject) -> str:
    source = subject.source()
    cut = int(len(source) * (subject.edge.fraction or 0))
    if len(subject.data) != cut:
        raise ValidationError(
            f"holds {len(subject.data):,} bytes, and {subject.edge.fraction:.0%} of "
            f"{subject.source_path} ({len(source):,} bytes) is {cut:,}"
        )
    if subject.data != source[: len(subject.data)]:
        raise ValidationError(f"is not a prefix of {subject.source_path}")
    tail = MISSING_TAIL.get(subject.claimed_format)
    if tail is None:
        raise ValidationError(
            f"is truncated, and nothing here says what that takes off a "
            f"{subject.claimed_format} (validators/edge.py MISSING_TAIL)"
        )
    return (
        f"Cut to {len(subject.data):,} of {len(source):,} bytes, the first "
        f"{subject.edge.fraction:.0%} of {subject.source_path}: {tail(subject.data)}."
    )


@_damage(Defect.MISMATCHED_EXTENSION)
def _damage_mismatched(subject: Subject) -> str:
    source = subject.source()
    if subject.data != source:
        raise ValidationError(f"is not {subject.source_path} byte for byte")
    signature = subject.data[:4].hex(" ").upper()
    return (
        f"The bytes are {subject.source_path} unchanged, starting with the "
        f"{subject.edge.intended_format.upper()} signature {signature}, while the file name "
        f"and the Content-Type announce {subject.claimed_format}."
    )


def _text(subject: Subject) -> str:
    """The file as text. A sentence that counts bytes has to be reading the real ones,
    so a file that is not UTF-8 is refused here rather than silently patched up."""
    try:
        return subject.data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"is not UTF-8, so its syntax is not what is wrong with it: {exc}"
        ) from exc


def _damage_json_syntax(subject: Subject) -> str:
    text = _text(subject)
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        stop = len(text[: exc.pos].encode())
        offsets = [
            len(text[: match.start()].encode()) for match in re.finditer(r",(\s*[}\]])", text)
        ]
        if not offsets:
            raise ValidationError(
                "is invalid JSON, but not for a comma before a closing bracket"
            ) from exc
        where = _and(f"{offset:,}" for offset in offsets)
        return (
            f"{len(offsets)} commas stand directly before a closing bracket (at bytes {where}), "
            f"and a JSON parser stops at byte {stop:,}, line {exc.lineno} column {exc.colno}."
        )
    raise ValidationError("parses as JSON, so nothing about its syntax is invalid")


def _damage_csv_syntax(subject: Subject) -> str:
    rows = [row for row in csv.reader(io.StringIO(_text(subject))) if row]
    widths = [len(row) for row in rows]
    if not rows:
        raise ValidationError("holds no rows at all, so no row is the odd one out")
    if len(set(widths)) == 1:
        raise ValidationError(f"has {widths[0]} fields in every row")
    odd = [
        f"row {index} carries {width}"
        for index, width in enumerate(widths, 1)
        if width != widths[0]
    ]
    return f"The header names {widths[0]} fields; of {len(rows)} rows, {_and(odd)}."


def _damage_xml_syntax(subject: Subject) -> str:
    try:
        etree.fromstring(subject.data, parser=_xml_parser())
    except etree.XMLSyntaxError as exc:
        line, column = exc.position
        opened = re.findall(rb"<([A-Za-z][\w.-]*)(?=[\s>])", subject.data)
        closed = re.findall(rb"</([A-Za-z][\w.-]*)\s*>", subject.data)
        unclosed = sorted(
            {name.decode() for name in opened if opened.count(name) > closed.count(name)}
        )
        if not unclosed:
            raise ValidationError(
                "is not well-formed, but every element it opens is closed"
            ) from exc
        counted = _and(
            f"{opened.count(name.encode())} <{name}> elements are opened and "
            f"{closed.count(name.encode())} closed"
            for name in unclosed
        )
        return f"{counted}, so an XML parser stops at line {line}, column {column}."
    raise ValidationError("is well-formed XML, so nothing about its syntax is invalid")


#: The syntax a file gets wrong is format-specific, and so is the sentence about it.
SYNTAX_DAMAGE: dict[str, Damage] = {
    "json": _damage_json_syntax,
    "csv": _damage_csv_syntax,
    "xml": _damage_xml_syntax,
}


@_damage(Defect.INVALID_SYNTAX)
def _damage_invalid_syntax(subject: Subject) -> str:
    writer = SYNTAX_DAMAGE.get(subject.claimed_format)
    if writer is None:
        raise ValidationError(
            f"has invalid {subject.claimed_format} syntax, and nothing here can say what is "
            "wrong with it (validators/edge.py SYNTAX_DAMAGE)"
        )
    return writer(subject)


@_damage(Defect.INVALID_ENCODING)
def _damage_invalid_encoding(subject: Subject) -> str:
    errors = _decode_errors(subject.data)
    if not errors:
        raise ValidationError("decodes as UTF-8, so its encoding is not invalid")
    places = _and(
        f"{data.hex(' ').upper()} at offset {offset:,} ({reason})"
        for offset, data, reason in errors
    )
    return f"{len(errors)} byte sequences are not UTF-8: {places}."


@_damage(Defect.BOM)
def _damage_bom(subject: Subject) -> str:
    """The mark is the whole defect, so what follows it has to be valid — otherwise the
    sentence would be describing the wrong problem."""
    mark = next((bom for bom in BOMS if subject.data.startswith(bom)), None)
    if mark is None:
        raise ValidationError("starts with no byte-order mark")
    rest = replace(subject, data=subject.data[len(mark) :])
    if not rest.accepts(subject.claimed_format):
        raise ValidationError(
            f"is not valid {subject.claimed_format} once the mark is removed, so the mark is "
            "not the only thing wrong with it"
        )
    return (
        f"The first {len(mark)} bytes are {mark.hex(' ').upper()}, a byte-order mark, before "
        f"an otherwise valid {subject.claimed_format.upper()} document of {len(rest.data):,} "
        "bytes."
    )


@_damage(Defect.HOSTILE_NAME)
def _damage_hostile_name(subject: Subject) -> str:
    names = _archive_names(subject.data)
    hostile = _escaping(names)
    if not hostile:
        raise ValidationError("holds no entry that escapes the extraction directory")
    listed = _and(
        f"entry {names.index(name) + 1} of {len(names)} is named {name!r}" for name in hostile
    )
    return (
        f"The archive itself is well formed and reads; {listed}, which climbs out of the "
        "directory it is extracted into."
    )


# --- the defect itself, asserted --------------------------------------------------------------

#: What every defect checker looks like: everything about the file, in, props out.
Checker = Callable[[Subject], dict[str, Any]]

#: One checker per defect. A table rather than a chain of branches: the closed enum in
#: catalog.py is the list of things that can be asserted, and this has to match it.
CHECKS: dict[Defect, Checker] = {}


def _checks(defect: Defect) -> Callable[[Checker], Checker]:
    def decorate(func: Checker) -> Checker:
        CHECKS[defect] = func
        return func

    return decorate


@_checks(Defect.ZERO_BYTE)
def _zero_byte(subject: Subject) -> dict[str, Any]:
    if subject.data:
        raise ValidationError(
            f"holds {len(subject.data)} bytes, and a zero-byte fixture holds none"
        )
    return {}


@_checks(Defect.TRUNCATED)
def _truncated(subject: Subject) -> dict[str, Any]:
    if not subject.data:
        raise ValidationError("is empty, so it is not a truncation of anything")
    if subject.accepts(subject.edge.intended_format) and _overrunning_box(subject.data) is None:
        raise ValidationError("still parses as its intended format, so it is not truncated")
    return {"fraction": subject.edge.fraction}


@_checks(Defect.MISMATCHED_EXTENSION)
def _mismatched_extension(subject: Subject) -> dict[str, Any]:
    expected = MAGIC.get(subject.edge.intended_format)
    if expected and not subject.data.startswith(expected):
        shown = " or ".join(prefix.hex() for prefix in expected)
        raise ValidationError(
            f"does not start with {subject.edge.intended_format} magic ({shown}): "
            "carrying the intended format's bytes is the point"
        )
    claimed = subject.claimed_format
    if claimed in MAGIC and subject.data.startswith(MAGIC[claimed]):
        raise ValidationError(f"starts with {claimed} magic, so the extension is not mismatched")
    return {}


@_checks(Defect.MAGIC_PREFIX)
def _magic_prefix(subject: Subject) -> dict[str, Any]:
    prefix = (subject.edge.magic or "").encode()
    if not subject.data.startswith(prefix):
        raise ValidationError(f"does not start with the declared magic {subject.edge.magic!r}")
    return {}


@_checks(Defect.INVALID_SYNTAX)
def _invalid_syntax(subject: Subject) -> dict[str, Any]:
    if subject.accepts(subject.edge.intended_format):
        raise ValidationError("parses as its intended format, so its syntax is not invalid")
    return {}


@_checks(Defect.INVALID_ENCODING)
def _invalid_encoding(subject: Subject) -> dict[str, Any]:
    try:
        subject.data.decode("utf-8")
    except UnicodeDecodeError:
        return {}
    raise ValidationError("decodes as UTF-8, so its encoding is not invalid")


@_checks(Defect.BOM)
def _bom(subject: Subject) -> dict[str, Any]:
    if not subject.data.startswith(BOMS):
        raise ValidationError("starts with no byte-order mark")
    return {}


@_checks(Defect.HOSTILE_NAME)
def _hostile_name(subject: Subject) -> dict[str, Any]:
    hostile = _escaping(_archive_names(subject.data))
    if not hostile:
        raise ValidationError("holds no entry that escapes the extraction directory")
    return {"hostile_entries": hostile}


# NONSTANDARD and STRESS assert nothing beyond the checks every fixture gets: what makes
# them edge cases is how a reader reacts to them, not anything measurable in the bytes.


@register("edge")
def validate_edge(data: bytes, fixture: Fixture, mime: str) -> dict[str, Any]:
    edge = fixture.edge
    if edge is None:  # pragma: no cover - the catalog model requires it
        raise ValidationError("has no edge block, which every edge fixture must declare")
    subject = Subject(data=data, fixture=fixture, edge=edge, mime=mime)

    props: dict[str, Any] = {
        "defect": edge.defect.value,
        "intended_format": edge.intended_format,
        "bytes": len(data),
    }
    if edge.source_fixture is not None:
        props["derived_from"] = edge.source_fixture

    check = CHECKS.get(edge.defect)
    if check is not None:
        props.update(check(subject))

    writer = DAMAGE.get(edge.defect)
    if writer is None:
        raise ValidationError(
            f"declares defect '{edge.defect.value}', and nothing here can describe the damage "
            "it does (validators/edge.py DAMAGE)"
        )
    props["damage"] = writer(subject)

    outcome, evidence = derive_outcome(subject)
    if outcome is not edge.outcome:
        raise ValidationError(
            f"the catalog declares outcome '{edge.outcome.value}' and the bytes say "
            f"'{outcome.value}': {evidence}"
        )
    props["outcome"] = outcome.value
    props["compare_with"] = edge.compare_with
    return props
