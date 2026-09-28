"""Edge-case fixtures — files that are deliberately wrong (docs/05 §3.13).

Every fixture here declares its defect in the catalog's `edge` block, and the validator
asserts that defect rather than the format's usual structure. Most of these files exist to
be rejected by whatever reads them, so "it parses" would be the wrong test — with one
exception: a `polyglot` is valid twice over, and both readers have to accept it.

The derived ones read their source through `ctx.dependency`, so a truncation is always a
prefix of the bytes that were actually published, not of a fresh build.
"""

from __future__ import annotations

import io
import json
import zipfile

from loremfile.generators.base import GeneratorContext, generator
from loremfile.util import lorem
from loremfile.util.zipnorm import DEFLATE_LEVEL, FILE_ATTR, ZIP_EPOCH

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


def _zip_into(prefix: bytes, name: str, payload: bytes, comment: bytes = b"") -> bytes:
    """Append an archive to bytes that are already something else.

    ``zipfile`` in append mode treats a non-archive prefix the way it treats a
    self-extracting stub: it writes the central directory with **absolute** offsets, so
    the result is a well-formed archive rather than one that only works with readers
    that tolerate a shifted directory. The entry conventions are zipnorm's, so the zip
    half looks like every other archive here.
    """
    buffer = io.BytesIO(prefix)
    buffer.seek(0, io.SEEK_END)
    with zipfile.ZipFile(buffer, "a", zipfile.ZIP_DEFLATED, compresslevel=DEFLATE_LEVEL) as archive:
        info = zipfile.ZipInfo(filename=name, date_time=ZIP_EPOCH)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = FILE_ATTR
        info.create_system = 3
        archive.writestr(info, payload)
        # The comment is the last thing in the file, which is how the PDF trailer can be
        # at the end of a file whose end also has to be a zip record.
        archive.comment = comment
    return buffer.getvalue()


@generator()
def pdf_zip_polyglot(ctx: GeneratorContext) -> bytes:
    """One file that is both a valid PDF and a valid zip archive.

    The two formats want opposite ends of the file: a PDF is read from the header down
    and ends with `startxref`/`%%EOF`, a zip is found by scanning back from the end for
    the end-of-central-directory record. They fit together because the zip record has a
    comment field: the PDF's trailer is written into it, so the same bytes end with a
    complete zip record *and* with a PDF trailer, and neither reader has to tolerate
    anything it would call damage.
    """
    body = lorem.sentence(ctx.rng).encode()
    content = b"BT /F1 24 Tf 72 760 Td (Polyglot) Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, object_body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + object_body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    out += trailer.encode("ascii")
    # The same trailer again, as the zip comment: the last `startxref` a PDF reader
    # finds scanning backwards is this one, and it names the same offset.
    return _zip_into(bytes(out), "readme.txt", body, comment=trailer.encode("ascii"))


@generator()
def gif_zip_polyglot(ctx: GeneratorContext) -> bytes:
    """One file that is both a valid GIF image and a valid zip archive.

    Easier than the PDF: a GIF ends at its trailer byte and decoders stop there, so the
    archive is simply everything after it. The image is a solid 4x4 square written by
    Pillow, small enough that the archive is most of the file.
    """
    from PIL import Image  # noqa: PLC0415 - only this generator needs it

    frame = io.BytesIO()
    Image.new("P", (4, 4), color=1).save(frame, format="GIF")
    return _zip_into(frame.getvalue(), "readme.txt", lorem.sentence(ctx.rng).encode())


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
