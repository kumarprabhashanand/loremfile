"""PDF fixtures (docs/05 §3.1).

fpdf2 writes a creation date, a producer and a creator into every document, and derives
the file ID from the content. All three are pinned here — the clock the determinism
guard provides is not enough on its own, because fpdf2 formats the date itself.

``a4-with-images-2pages.pdf`` is the catalog's first fixture built from other published
fixtures. It reads them through ``ctx.dependency``, which never regenerates a published
file: it takes the bytes that were actually published, so this PDF stays stable even if
the PNG generator changes later.
"""

from __future__ import annotations

import datetime as dt
import io

from fpdf import FPDF
from fpdf.enums import AccessPermission
from PIL import Image

from loremfile.config import APPROX_TOLERANCE
from loremfile.generators.base import GeneratorContext, generator
from loremfile.util import lorem
from loremfile.util.sizing import fit

#: Every document reports this instant. fpdf2 formats the date itself, so patching the
#: clock is not sufficient — it has to be set explicitly.
FIXED_DATE = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)

PAGE_SIZES = {"a4": "A4", "letter": "Letter", "a5": "A5"}

#: The core fonts are Latin-1 only, and these fixtures deliberately embed no font
#: (docs/05 §3.1). Anything outside Latin-1 — an em dash, a curly quote — makes fpdf2
#: raise, which is the correct behaviour and is why every string here stays in range.
CORE_FONT_ENCODING = "latin-1"

#: Paragraph count that fits one A4 page at 11pt with 14pt leading.
PARAGRAPHS_PER_PAGE = 2

#: Columns narrow enough to fit a portrait A4 table.
TABLE_COLUMNS = ("id", "first_name", "last_name", "city", "country", "is_active")


def _document(page_size: str = "a4", orientation: str = "portrait") -> FPDF:
    pdf = FPDF(orientation=orientation, unit="pt", format=PAGE_SIZES[page_size])
    pdf.set_creation_date(FIXED_DATE)
    pdf.set_producer("loremfile.dev")
    pdf.set_creator("loremfile.dev")
    pdf.set_title("loremfile.dev sample PDF")
    pdf.set_author("loremfile.dev")
    pdf.set_lang("en-GB")
    return pdf


def _render(pdf: FPDF) -> bytes:
    return bytes(pdf.output())


@generator()
def basic(
    ctx: GeneratorContext,
    *,
    pages: int,
    page_size: str = "a4",
    orientation: str = "portrait",
    page_numbers: bool = False,
    accents: bool = False,
) -> bytes:
    """Lorem body text in the Helvetica core font, no embedded fonts."""
    rng = ctx.rng
    pdf = _document(page_size, orientation)
    for number in range(1, pages + 1):
        pdf.add_page()
        pdf.set_font("helvetica", "B", 18)
        pdf.cell(0, 24, f"loremfile.dev - page {number} of {pages}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)
        pdf.set_font("helvetica", "", 11)
        # Two paragraphs fill an A4 page without triggering fpdf2's automatic page
        # break. Five overflowed, so every requested page produced two and `pages`
        # came out doubled — caught by the validator, not by looking at the file.
        for _ in range(PARAGRAPHS_PER_PAGE):
            text = lorem.paragraph(rng)
            if accents:
                text = f"{text} Accents: é à ü ñ ø ç."
            pdf.multi_cell(0, 14, text, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
        if page_numbers:
            # Writing at the bottom margin triggers fpdf2's automatic page break, which
            # silently doubled the page count: a4-3pages produced six. Disabling it for
            # the footer alone keeps `pages` exactly what the catalog asks for.
            pdf.set_auto_page_break(auto=False)
            pdf.set_y(-40)
            pdf.set_font("helvetica", "I", 9)
            pdf.cell(0, 12, f"{number} / {pages}", align="C")
            pdf.set_auto_page_break(auto=True, margin=28.35)
    return _render(pdf)


@generator()
def blank(_ctx: GeneratorContext, *, pages: int = 1) -> bytes:
    """A valid PDF with pages but no text at all — a common upload edge case."""
    pdf = _document()
    for _ in range(pages):
        pdf.add_page()
    return _render(pdf)


@generator()
def minimal(_ctx: GeneratorContext) -> bytes:
    """A hand-written PDF: one page, the word "Hello", nothing else.

    Written byte by byte rather than through fpdf2 because the point of this fixture is
    to be the smallest structurally valid PDF, and a library will always add more than
    the format requires. The cross-reference offsets are computed from the objects, so
    the file stays valid if the text ever changes.
    """
    # The stream body and its declared /Length must agree exactly. Hardcoding the
    # number is how they drift: the first version said 44 for a 37-byte stream, and
    # `qpdf --check` caught it with "attempting to recover stream length".
    content = b"BT /F1 24 Tf 72 760 Td (Hello) Tj ET\n"
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
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


@generator()
def with_table(ctx: GeneratorContext, *, rows: int = 10) -> bytes:
    """A single page holding a table of the shared people dataset."""
    pdf = _document()
    pdf.add_page()
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 22, "People", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("helvetica", "", 9)
    with pdf.table(col_widths=(30, 70, 80, 80, 40, 40)) as table:
        header = table.row()
        for column in TABLE_COLUMNS:
            header.cell(column)
        for record in ctx.dataset("people", rows):
            line = table.row()
            for column in TABLE_COLUMNS:
                value = record[column]
                line.cell("yes" if value is True else "no" if value is False else str(value))
    return _render(pdf)


@generator()
def with_images(ctx: GeneratorContext, *, png: str, jpg: str) -> bytes:
    """Two pages, each embedding a published image fixture.

    The bytes come from ``ctx.dependency``, which resolves to what was actually
    published rather than regenerating — so this PDF does not change if an image
    generator is refactored later.
    """
    pdf = _document()
    for label, path in (("PNG", png), ("JPEG", jpg)):
        payload = ctx.dependency(path)
        pdf.add_page()
        pdf.set_font("helvetica", "B", 14)
        pdf.cell(0, 20, f"Embedded {label}: {path}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(8)
        pdf.image(io.BytesIO(payload), w=400)
    return _render(pdf)


@generator()
def encrypted(
    ctx: GeneratorContext,
    *,
    user_password: str,
    owner_password: str,
    pages: int = 1,
) -> bytes:
    """An AES-128 encrypted PDF. Both passwords are in the fixture's description.

    fpdf2 draws the encryption IV from ``os.urandom``, which the determinism guard
    patches — but that is an assumption about a library's internals, so the run-twice
    test in this milestone's suite is what actually proves it.
    """
    rng = ctx.rng
    pdf = _document()
    pdf.set_encryption(
        owner_password=owner_password,
        user_password=user_password,
        permissions=AccessPermission.PRINT_LOW_RES | AccessPermission.COPY,
        encrypt_metadata=False,
    )
    for _ in range(pages):
        pdf.add_page()
        pdf.set_font("helvetica", "B", 16)
        pdf.cell(0, 22, "Encrypted sample", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)
        pdf.set_font("helvetica", "", 11)
        pdf.multi_cell(0, 14, lorem.paragraph(rng), new_x="LMARGIN", new_y="NEXT")
    return _render(pdf)


#: One 512-wide plate at quality 90 is about 236 KB, which is the granularity the page
#: count alone would give. docs/05 §6 said "n = pages"; that cannot hit a 5 % window —
#: for a 1 MB target, four plates give 946 KB and five give 1.18 MB, and the tolerance
#: band sits in the gap. The page count is therefore derived from the target and the
#: fitted parameter is the plate *height*, which moves the total smoothly and linearly.
PLATE_WIDTH = 512
APPROX_PLATE_BYTES = 236_000


@generator(parallel_safe=False)
def sized(ctx: GeneratorContext, *, size: int) -> bytes:
    """A4 pages each embedding one incompressible seeded-noise JPEG (docs/05 §6)."""
    pages = max(1, round(size / APPROX_PLATE_BYTES))

    def plate(index: int, height: int) -> bytes:
        needed = PLATE_WIDTH * height * 3
        noise = ctx.stream(needed + pages)[index : index + needed]
        image = Image.frombytes("RGB", (PLATE_WIDTH, height), noise)
        buffer = io.BytesIO()
        # Default 4:2:0 subsampling, which matches the ~250 KB docs/05 §6 estimates.
        image.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()

    def make(height: int) -> bytes:
        pdf = _document()
        for index in range(pages):
            pdf.add_page()
            pdf.set_font("helvetica", "", 10)
            pdf.cell(0, 14, f"Plate {index + 1} of {pages}", new_x="LMARGIN", new_y="NEXT")
            pdf.image(io.BytesIO(plate(index, height)), w=360)
        return _render(pdf)

    start_height = max(size // (pages * PLATE_WIDTH * 2), 16)
    _, payload = fit(size, APPROX_TOLERANCE, make, n0=start_height, n_min=16, n_max=20_000)
    return payload
