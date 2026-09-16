"""Validator for the edge cases (docs/06 §6, docs/05 §3.13).

Every other validator asks "is this a good file of its format?". This one asks the
opposite: the catalog declares a defect, and the fixture has to *have* that defect. A
truncated PDF that somehow parses, or a zero-byte file with bytes in it, is a broken
fixture even though nothing crashed — so each defect is asserted directly, and the
intended format's own validator is the negative control where that is the test.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from typing import Any

from loremfile.catalog import Defect, Edge, Fixture
from loremfile.validators import MAGIC, ValidationError, has_validator, register, validator_for

#: A byte-order mark for each encoding an edge fixture may carry.
BOMS = (b"\xef\xbb\xbf", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff", b"\xff\xfe", b"\xfe\xff")

#: What every defect checker looks like: the bytes, the row, and the declared defect.
Checker = Callable[[bytes, Fixture, Edge], dict[str, Any]]

#: One checker per defect. A table rather than a chain of branches: the closed enum in
#: catalog.py is the list of things that can be asserted, and this has to match it.
CHECKS: dict[Defect, Checker] = {}


def _checks(defect: Defect) -> Callable[[Checker], Checker]:
    def decorate(func: Checker) -> Checker:
        CHECKS[defect] = func
        return func

    return decorate


def _intended_accepts(data: bytes, fixture: Fixture) -> bool:
    """Whether the intended format's own validator accepts these bytes."""
    intended = fixture.edge.intended_format if fixture.edge else ""
    if not has_validator(intended):
        return False
    try:
        validator_for(intended)(data, fixture, fixture.mime or "application/octet-stream")
    except Exception:  # any reader refusing these bytes is the result we want
        return False
    return True


@_checks(Defect.ZERO_BYTE)
def _zero_byte(data: bytes, _fixture: Fixture, _edge: Edge) -> dict[str, Any]:
    if data:
        raise ValidationError(f"holds {len(data)} bytes, and a zero-byte fixture holds none")
    return {}


#: An ISO-BMFF box header: a four-byte size followed by a four-byte type.
BOX_HEADER_BYTES = 8


def _boxes_overrun(data: bytes) -> bool:
    """Whether an ISO-BMFF file ends inside a box that claims more bytes than remain.

    ffprobe reads a truncated MP4 without complaint — the header is intact and the streams
    are described — so "its own validator rejects it" does not detect truncation for this
    container. The box table does: the file stops inside a box whose declared size runs
    past the end. Only applied to files that actually carry an `ftyp` box.
    """
    if data[4:8] != b"ftyp":
        return False
    offset = 0
    while offset + BOX_HEADER_BYTES <= len(data):
        size = int.from_bytes(data[offset : offset + 4], "big")
        if size == 1:  # the real, 64-bit size follows the box type
            if offset + 16 > len(data):
                return True
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
        elif size == 0:  # runs to the end of the file by definition, so never short
            return False
        if (
            size < BOX_HEADER_BYTES
        ):  # not a box table this understands; leave the verdict to the caller
            return False
        if offset + size > len(data):
            return True
        offset += size
    return False


@_checks(Defect.TRUNCATED)
def _truncated(data: bytes, fixture: Fixture, edge: Edge) -> dict[str, Any]:
    if not data:
        raise ValidationError("is empty, so it is not a truncation of anything")
    if _intended_accepts(data, fixture) and not _boxes_overrun(data):
        raise ValidationError("still parses as its intended format, so it is not truncated")
    return {"fraction": edge.fraction}


@_checks(Defect.MISMATCHED_EXTENSION)
def _mismatched_extension(data: bytes, fixture: Fixture, edge: Edge) -> dict[str, Any]:
    expected = MAGIC.get(edge.intended_format)
    if expected and not data.startswith(expected):
        shown = " or ".join(prefix.hex() for prefix in expected)
        raise ValidationError(
            f"does not start with {edge.intended_format} magic ({shown}): "
            "carrying the intended format's bytes is the point"
        )
    if fixture.ext in MAGIC and data.startswith(MAGIC[fixture.ext]):
        raise ValidationError(
            f"starts with {fixture.ext} magic, so the extension is not mismatched"
        )
    return {}


@_checks(Defect.MAGIC_PREFIX)
def _magic_prefix(data: bytes, _fixture: Fixture, edge: Edge) -> dict[str, Any]:
    prefix = (edge.magic or "").encode()
    if not data.startswith(prefix):
        raise ValidationError(f"does not start with the declared magic {edge.magic!r}")
    return {}


@_checks(Defect.INVALID_SYNTAX)
def _invalid_syntax(data: bytes, fixture: Fixture, _edge: Edge) -> dict[str, Any]:
    if _intended_accepts(data, fixture):
        raise ValidationError("parses as its intended format, so its syntax is not invalid")
    return {}


@_checks(Defect.INVALID_ENCODING)
def _invalid_encoding(data: bytes, _fixture: Fixture, _edge: Edge) -> dict[str, Any]:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return {}
    raise ValidationError("decodes as UTF-8, so its encoding is not invalid")


@_checks(Defect.BOM)
def _bom(data: bytes, _fixture: Fixture, _edge: Edge) -> dict[str, Any]:
    if not data.startswith(BOMS):
        raise ValidationError("starts with no byte-order mark")
    return {}


@_checks(Defect.HOSTILE_NAME)
def _hostile_name(data: bytes, _fixture: Fixture, _edge: Edge) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"is not a readable archive: {exc}") from exc
    hostile = [name for name in names if name.startswith(("/", "../")) or "/../" in name]
    if not hostile:
        raise ValidationError("holds no entry that escapes the extraction directory")
    return {"hostile_entries": hostile}


# NONSTANDARD and STRESS assert nothing beyond the checks every fixture gets: what makes
# them edge cases is how a reader reacts to them, not anything measurable in the bytes.


@register("edge")
def validate_edge(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    edge = fixture.edge
    if edge is None:  # pragma: no cover - the catalog model requires it
        raise ValidationError("has no edge block, which every edge fixture must declare")

    props: dict[str, Any] = {
        "defect": edge.defect.value,
        "intended_format": edge.intended_format,
        "bytes": len(data),
    }
    check = CHECKS.get(edge.defect)
    if check is not None:
        props.update(check(data, fixture, edge))
    return props
