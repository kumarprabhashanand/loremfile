"""Validator for text-like formats (docs/04 §1.3).

Props: ``encoding``, ``bom``, ``line_ending``, ``lines``, ``max_line_bytes``.

Line endings and line counts are measured **on the bytes**, not on a decoded string, so
a mixed-ending file is reported as mixed rather than silently normalised by Python's
universal newlines.
"""

from __future__ import annotations

from typing import Any

from loremfile.catalog import Fixture
from loremfile.validators import ValidationError, charset_of, register

BOMS: tuple[tuple[bytes, str], ...] = (
    # Longest first: the UTF-32LE BOM starts with the UTF-16LE BOM.
    (b"\xff\xfe\x00\x00", "utf-32le"),
    (b"\x00\x00\xfe\xff", "utf-32be"),
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe", "utf-16le"),
    (b"\xfe\xff", "utf-16be"),
)

#: Formats whose props are exactly the text ones (docs/04 §1.3). csv, tsv, json, xml,
#: yaml and toml are text too, but they carry extra format-specific props, so their
#: validators live in validators/data.py and call `text_props` from here.
TEXT_FORMATS = ("txt", "md", "log", "ini", "html", "css", "js", "srt", "vtt", "sql", "rtf")


def detect_bom(data: bytes) -> tuple[bool, str | None]:
    for marker, name in BOMS:
        if data.startswith(marker):
            return True, name
    return False, None


def measure_line_endings(data: bytes) -> tuple[str, int]:
    """Return the line-ending style and the line count, counted on raw bytes."""
    crlf = data.count(b"\r\n")
    cr = data.count(b"\r") - crlf
    lf = data.count(b"\n") - crlf
    kinds = [name for name, count in (("crlf", crlf), ("cr", cr), ("lf", lf)) if count]
    if not kinds:
        return "none", 1 if data else 0
    style = kinds[0] if len(kinds) == 1 else "mixed"
    total = crlf + cr + lf
    # A file not ending in a terminator still has a final line.
    if data and not data.endswith((b"\n", b"\r")):
        total += 1
    return style, total


def _max_line_bytes(data: bytes) -> int:
    normalised = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return max((len(line) for line in normalised.split(b"\n")), default=0)


def text_props(data: bytes, mime: str) -> dict[str, Any]:
    charset = charset_of(mime) or "utf-8"
    has_bom, bom_encoding = detect_bom(data)
    try:
        data.decode(charset, errors="strict")
    except (UnicodeDecodeError, LookupError) as exc:
        raise ValidationError(f"does not decode as {charset}: {exc}") from exc

    if has_bom and bom_encoding and not charset.startswith(bom_encoding[:6]):
        raise ValidationError(f"has a {bom_encoding} BOM but declares charset {charset}")

    line_ending, lines = measure_line_endings(data)
    return {
        "encoding": charset,
        "bom": has_bom,
        "line_ending": line_ending,
        "lines": lines,
        "max_line_bytes": _max_line_bytes(data),
    }


def make_validator(fmt: str) -> None:
    """Register the shared text validator under one format name."""

    @register(fmt)
    def _validate(data: bytes, _fixture: Fixture, mime: str) -> dict[str, Any]:
        return text_props(data, mime)


for _format in TEXT_FORMATS:
    make_validator(_format)
