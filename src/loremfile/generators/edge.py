"""Edge-case fixtures — files that are deliberately wrong (docs/05 §3.13).

Every fixture here declares its defect in the catalog's `edge` block, and the validator
asserts that defect rather than the format's usual structure: these files exist to be
rejected by whatever reads them, so "it parses" would be the wrong test.

The derived ones read their source through `ctx.dependency`, so a truncation is always a
prefix of the bytes that were actually published, not of a fresh build.
"""

from __future__ import annotations

import io
import json
import zipfile

from loremfile.generators.base import GeneratorContext, generator
from loremfile.util import lorem
from loremfile.util.zipnorm import ZIP_EPOCH

#: The entry name a hostile archive uses to escape its extraction directory.
TRAVERSAL_NAME = "../evil.txt"


@generator()
def zero_byte(_ctx: GeneratorContext) -> bytes:
    """Nothing at all. The file exists, has a content type, and holds no bytes."""
    return b""


@generator()
def truncated(ctx: GeneratorContext, *, source: str, fraction: float) -> bytes:
    """The first `fraction` of a published fixture, rounded down to a whole byte.

    Read through `ctx.dependency`, so this is a prefix of the bytes that were published
    rather than of a rebuild that might differ.
    """
    data = ctx.dependency(source)
    return data[: int(len(data) * fraction)]


@generator()
def copied(ctx: GeneratorContext, *, source: str) -> bytes:
    """A published fixture's bytes under a name claiming another format."""
    return ctx.dependency(source)


@generator()
def json_trailing_comma(ctx: GeneratorContext) -> bytes:
    """JSON with a trailing comma: valid JavaScript, invalid JSON (RFC 8259)."""
    rng = ctx.rng
    return (
        "{\n"
        f'  "name": "{lorem.words(rng, 1)[0]}",\n'
        '  "count": 3,\n'
        '  "tags": ["one", "two",],\n'
        "}\n"
    ).encode()


@generator()
def json_bom(ctx: GeneratorContext) -> bytes:
    """Valid JSON preceded by a UTF-8 byte-order mark, which RFC 8259 forbids."""
    document = {"name": lorem.words(ctx.rng, 1)[0], "count": 3, "tags": ["one", "two"]}
    return b"\xef\xbb\xbf" + (json.dumps(document, indent=2) + "\n").encode()


@generator()
def csv_ragged_rows(ctx: GeneratorContext) -> bytes:
    """A CSV whose rows have different field counts, which strict readers refuse."""
    rng = ctx.rng
    rows = [
        "id,name,city",
        "1,alpha,berlin",
        "2,beta",  # one field short
        "3,gamma,paris,extra",  # one field long
        f"4,{lorem.words(rng, 1)[0]},rome",
    ]
    return ("\n".join(rows) + "\n").encode()


@generator()
def xml_unclosed_tag(ctx: GeneratorContext) -> bytes:
    """XML with an element that is never closed: not well-formed, so no parser may accept it."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<catalog>\n"
        f"  <item><name>{lorem.words(ctx.rng, 2)[0]}</name>\n"
        "  <item><name>second</name></item>\n"
        "</catalog>\n"
    ).encode()


@generator()
def utf8_invalid_bytes(ctx: GeneratorContext) -> bytes:
    """Text that is valid ASCII either side of a byte sequence UTF-8 does not allow."""
    head = lorem.sentence(ctx.rng).encode()
    # 0xC3 starts a two-byte sequence; 0x28 cannot continue one. 0xA0 is a bare
    # continuation byte with nothing before it.
    return head + b"\n\xc3\x28 and a stray \xa0 byte\n"


@generator()
def zip_traversal_name(ctx: GeneratorContext) -> bytes:
    """A zip whose entry name climbs out of the extraction directory.

    The archive is otherwise ordinary: the defect is the name, and an extractor that
    joins it to a destination path without sanitising writes outside that directory.
    """
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("readme.txt", TRAVERSAL_NAME):
            info = zipfile.ZipInfo(filename=name, date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, lorem.text(ctx.rng, 1).encode())
    return out.getvalue()
