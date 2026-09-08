"""M3.4 PDF: generators, validators, negative tests, determinism tests.

The encrypted fixture is the interesting one. docs/06 §4 claims fpdf2's encryption IV
comes from the patched ``os.urandom`` — a Python-level call the determinism guard does
reach. That claim is *plausible*, which is exactly what made fastavro's equivalent claim
dangerous, so it is proved here rather than assumed.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pypdf
import pytest

from loremfile import build as build_module
from loremfile import datasets
from loremfile.build import load_generators
from loremfile.catalog import Catalog, Fixture
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import _REGISTRY, ValidationError, load, validate

WORKDIR = Path(tempfile.gettempdir())
CATALOG = Catalog.load()
load_generators()
load()

# S105: this password is published on purpose — docs/05 §3.1 puts it in the
# fixture description, because an encrypted fixture nobody can open is useless.
USER_PASSWORD = "loremfile"  # noqa: S105


def fixture(path: str) -> Fixture:
    return CATALOG.by_path[path]


def build(path: str, resolver=None) -> bytes:
    entry = fixture(path)
    context = GeneratorContext(path=path, workdir=WORKDIR)
    if resolver is not None:
        context._dependency = resolver
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **entry.params)
    assert isinstance(out, bytes)
    return out


def built_bytes(path: str) -> bytes:
    """Read a fixture the build already produced, for the dependency case."""
    target = build_module.fixtures_dir() / path
    if not target.is_file():
        pytest.skip(f"run `loremfile build --only {path}` first")
    return target.read_bytes()


def check(path: str) -> dict:
    entry = fixture(path)
    report = validate(build(path), entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures
    return report.props


def measure(path: str, payload: bytes) -> dict:
    entry = fixture(path)
    return _REGISTRY["pdf"](payload, entry, CATALOG.mime_for(entry))


# --- page geometry ---------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "pages", "width", "height"),
    [
        ("pdf/a4-1page.pdf", 1, 595.28, 841.89),
        ("pdf/a4-3pages.pdf", 3, 595.28, 841.89),
        ("pdf/a4-10pages.pdf", 10, 595.28, 841.89),
        ("pdf/letter-1page.pdf", 1, 612.0, 792.0),
        ("pdf/a4-landscape-1page.pdf", 1, 841.89, 595.28),
    ],
)
def test_page_count_and_box(path: str, pages: int, width: float, height: float) -> None:
    """Page count is exact. It was not at first: the footer tripped fpdf2's automatic
    page break and every requested page produced two."""
    props = check(path)
    assert props["pages"] == pages
    assert props["page_width_pt"] == pytest.approx(width, abs=0.01)
    assert props["page_height_pt"] == pytest.approx(height, abs=0.01)


def test_landscape_really_is_wider_than_tall() -> None:
    props = check("pdf/a4-landscape-1page.pdf")
    assert props["page_width_pt"] > props["page_height_pt"]


def test_blank_pdf_is_valid_but_empty() -> None:
    props = check("pdf/blank-1page.pdf")
    assert props["pages"] == 1
    assert props["has_images"] is False


# --- the hand-written minimal file ----------------------------------------


def test_minimal_pdf_is_small_and_valid() -> None:
    payload = build("pdf/minimal.pdf")
    assert payload.startswith(b"%PDF-")
    assert payload.rstrip().endswith(b"%%EOF")
    assert len(payload) < 1024, "the point of this fixture is to be tiny"
    assert check("pdf/minimal.pdf")["pages"] == 1


def test_minimal_pdf_declares_its_real_stream_length() -> None:
    """The first version hardcoded 44 for a 37-byte stream; qpdf caught it."""
    payload = build("pdf/minimal.pdf")
    declared = int(payload.split(b"/Length ")[1].split(b" ")[0])
    stream = payload.split(b"stream\n", 1)[1].split(b"endstream", 1)[0]
    assert declared == len(stream)


def test_minimal_pdf_offsets_point_at_real_objects() -> None:
    """A cross-reference table with wrong offsets is the classic hand-written PDF bug."""
    payload = build("pdf/minimal.pdf")
    xref_at = int(payload.rsplit(b"startxref\n", 1)[1].split(b"\n", 1)[0])
    assert payload[xref_at : xref_at + 4] == b"xref"
    for line in payload[xref_at:].splitlines()[2:7]:
        offset = int(line.split()[0])
        if offset:
            assert payload[offset : offset + 1].isdigit()
            assert b" 0 obj" in payload[offset : offset + 20]


# --- encryption ------------------------------------------------------------


def test_encrypted_pdf_needs_the_published_password() -> None:
    payload = build("pdf/a4-encrypted-1page.pdf")
    reader = pypdf.PdfReader(io.BytesIO(payload))
    assert reader.is_encrypted
    assert reader.decrypt("wrong-password") == pypdf.PasswordType.NOT_DECRYPTED
    assert reader.decrypt(USER_PASSWORD) != pypdf.PasswordType.NOT_DECRYPTED
    assert len(reader.pages) == 1


def test_encrypted_pdf_password_is_in_the_description() -> None:
    """An encrypted fixture nobody can open is useless, so the password is published."""
    entry = fixture("pdf/a4-encrypted-1page.pdf")
    assert USER_PASSWORD in entry.description
    assert entry.params["user_password"] == USER_PASSWORD


def test_encryption_is_deterministic() -> None:
    """docs/06 §4 claims the IV comes from the patched os.urandom. Prove it."""
    assert build("pdf/a4-encrypted-1page.pdf") == build("pdf/a4-encrypted-1page.pdf")


def test_validator_reports_encrypted_and_opens_it() -> None:
    assert check("pdf/a4-encrypted-1page.pdf")["encrypted"] is True


# --- content ---------------------------------------------------------------


def test_table_pdf_contains_people_data() -> None:
    payload = build("pdf/a4-with-table-1page.pdf")
    reader = pypdf.PdfReader(io.BytesIO(payload))
    text = reader.pages[0].extract_text()
    person = datasets.rows("people", 1)[0]
    assert person["first_name"] in text
    assert person["city"] in text


def test_images_pdf_embeds_the_published_bytes() -> None:
    """The dependency mechanism: built from what was published, not regenerated."""
    resolver = built_bytes
    payload = build("pdf/a4-with-images-2pages.pdf", resolver=resolver)
    props = measure("pdf/a4-with-images-2pages.pdf", payload)
    assert props["pages"] == 2
    assert props["has_images"] is True


def test_images_pdf_declares_its_dependencies() -> None:
    entry = fixture("pdf/a4-with-images-2pages.pdf")
    assert set(entry.depends_on) == {"png/640x480.png", "jpg/640x480.jpg"}


@pytest.mark.parametrize(("path", "target"), [("pdf/1mb.pdf", 10**6)])
def test_sized_pdf_lands_inside_the_tolerance(path: str, target: int) -> None:
    assert abs(len(build(path)) - target) <= 0.05 * target


# --- determinism -----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "pdf/a4-1page.pdf",
        "pdf/a4-3pages.pdf",
        "pdf/letter-1page.pdf",
        "pdf/a4-landscape-1page.pdf",
        "pdf/blank-1page.pdf",
        "pdf/minimal.pdf",
        "pdf/a4-with-table-1page.pdf",
        "pdf/a4-encrypted-1page.pdf",
        "pdf/1mb.pdf",
    ],
)
def test_running_twice_gives_identical_bytes(path: str) -> None:
    assert build(path) == build(path)


# --- negative tests --------------------------------------------------------


def test_truncated_pdf_is_rejected() -> None:
    entry = fixture("pdf/a4-1page.pdf")
    report = validate(build("pdf/a4-1page.pdf")[:300], entry, CATALOG.mime_for(entry))
    assert not report.ok


def test_a_file_without_the_pdf_header_is_rejected() -> None:
    entry = fixture("pdf/a4-1page.pdf")
    report = validate(b"not a pdf at all\n", entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("magic" in f for f in report.failures)


def test_qpdf_catches_a_broken_cross_reference_table() -> None:
    """pypdf recovers from a wrong startxref; qpdf is the second opinion that does not."""
    payload = bytearray(build("pdf/minimal.pdf"))
    marker = payload.rfind(b"startxref\n")
    end = payload.find(b"\n", marker + 10)
    payload[marker + 10 : end] = b"999999"
    with pytest.raises(ValidationError):
        measure("pdf/minimal.pdf", bytes(payload))


def test_encrypted_pdf_with_the_wrong_declared_password_fails_validation() -> None:
    entry = fixture("pdf/a4-encrypted-1page.pdf")
    wrong = entry.model_copy(update={"params": {**entry.params, "user_password": "nope"}})
    payload = build("pdf/a4-encrypted-1page.pdf")
    with pytest.raises(ValidationError, match="does not open it"):
        _REGISTRY["pdf"](payload, wrong, CATALOG.mime_for(entry))
