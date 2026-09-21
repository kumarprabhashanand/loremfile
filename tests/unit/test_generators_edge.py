"""M3.8 edge cases: each fixture's declared defect, asserted and negatively controlled.

These files exist to be rejected, so the tests are the mirror image of every other
generator test: the positive case is that the defect is really there, and the negative
case feeds the validator a *correct* file and requires it to complain. A validator that
accepted anything would pass the first kind of test and fail every one of the second.

Derived rows (`truncated`, `copied`) read their source through `ctx.dependency`, so they
are tested with a stub resolver: what matters is that they read the published path and
cut it where the catalog says, not that a PDF can be rebuilt on this machine.
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path

import pytest

from loremfile.catalog import Catalog, Fixture
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import load as load_validators
from loremfile.validators import validate

load_validators()  # the edge validator runs other formats' validators as controls

CATALOG = Catalog.load()
WORKDIR = Path(tempfile.gettempdir())
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
PDF_HEADER = b"%PDF-1.7\n%\xc7\xec\x8f\xa2\n"


def fixture(path: str) -> Fixture:
    return CATALOG.by_path[path]


def edge_fixtures() -> list[str]:
    return [f.path for f in CATALOG.fixtures() if f.format == "edge"]


def standalone() -> list[str]:
    return [p for p in edge_fixtures() if not fixture(p).depends_on]


def build(path: str, *, dependency: bytes | None = None) -> bytes:
    entry = fixture(path)
    ctx = GeneratorContext(
        path=path,
        workdir=WORKDIR,
        _dependency=lambda _p: dependency if dependency is not None else b"",
    )
    with deterministic(ctx.seed):
        out = REGISTRY.get(entry.generator)(ctx, **entry.params)
    return out.read_bytes() if isinstance(out, Path) else out


def check(path: str, payload: bytes | None = None) -> dict:
    entry = fixture(path)
    report = validate(
        payload if payload is not None else build(path), entry, CATALOG.mime_for(entry)
    )
    assert report.ok, report.failures
    return report.props


def refused(path: str, payload: bytes) -> str:
    """The failures reported for bytes that do *not* carry the declared defect."""
    entry = fixture(path)
    report = validate(payload, entry, CATALOG.mime_for(entry))
    assert not report.ok, f"{path} accepted bytes that are not defective"
    return " | ".join(report.failures)


# --- the catalogue this file is about --------------------------------------


def test_every_edge_row_declares_its_defect_and_intended_format() -> None:
    for path in edge_fixtures():
        entry = fixture(path)
        assert entry.edge is not None, f"{path} has no edge block"
        assert entry.edge_case is True
        assert entry.edge.intended_format in {f.format for f in CATALOG.fixtures()}


def test_a_derived_row_depends_on_the_fixture_its_edge_block_names() -> None:
    """`depends_on` drives the build order; `edge.source_fixture` documents the defect.

    They are separate fields, so nothing but a test stops them drifting apart — and a
    truncation whose build order is wrong reads bytes that do not exist yet.
    """
    for path in edge_fixtures():
        entry = fixture(path)
        assert entry.edge is not None
        source = entry.edge.source_fixture
        if source is None:
            assert not entry.depends_on, f"{path} depends on something it does not declare"
            continue
        assert source in entry.depends_on, f"{path}: {source} missing from depends_on"
        assert entry.params.get("source") == source, f"{path}: params.source != source_fixture"
        assert source in CATALOG.by_path, f"{path}: {source} is not a catalogued fixture"


# --- zero-byte --------------------------------------------------------------


@pytest.mark.parametrize("path", [p for p in edge_fixtures() if "zero-byte" in p])
def test_a_zero_byte_fixture_really_holds_nothing(path: str) -> None:
    assert build(path) == b""
    assert check(path)["bytes"] == 0


def test_a_zero_byte_fixture_with_bytes_in_it_is_refused() -> None:
    assert "zero-byte fixture holds none" in refused("edge/zero-byte.pdf", PDF_HEADER)


# --- truncation -------------------------------------------------------------


def test_truncation_cuts_the_published_bytes_where_the_catalog_says() -> None:
    source = bytes(range(100))
    assert build("edge/pdf-truncated-60pct.pdf", dependency=source) == source[:60]
    assert build("edge/zip-truncated-50pct.zip", dependency=source) == source[:50]


def test_truncation_reads_the_published_path_not_a_rebuild() -> None:
    """A rebuild could differ from what was published; the prefix has to match the file."""
    asked: list[str] = []
    entry = fixture("edge/jpg-truncated-50pct.jpg")
    ctx = GeneratorContext(
        path=entry.path,
        workdir=WORKDIR,
        _dependency=lambda p: (asked.append(p), bytes(64))[1],
    )
    with deterministic(ctx.seed):
        REGISTRY.get(entry.generator)(ctx, **entry.params)
    assert asked == [entry.edge.source_fixture]


def test_a_truncated_fixture_that_still_parses_is_refused() -> None:
    """A *whole* archive under the truncated name must fail: it reads, so nothing is cut.

    Built here rather than taken from a fixture, because the control needs bytes the zip
    validator actually accepts — feeding it something it rejects for another reason would
    pass this test while proving nothing.
    """
    whole = io.BytesIO()
    with zipfile.ZipFile(whole, "w") as archive:
        archive.writestr("readme.txt", "a complete, readable archive")
    assert "not truncated" in refused("edge/zip-truncated-50pct.zip", whole.getvalue())
    assert "not a truncation" in refused("edge/zip-truncated-50pct.zip", b"")


# --- mismatched extension ---------------------------------------------------


def test_the_mislabelled_file_carries_the_intended_format_bytes() -> None:
    props = check("edge/png-with-pdf-extension.pdf", PNG_HEADER)
    assert props["intended_format"] == "png"
    assert props["defect"] == "mismatched-extension"


def test_a_file_that_matches_its_extension_is_refused() -> None:
    failures = refused("edge/png-with-pdf-extension.pdf", PDF_HEADER)
    assert "pdf magic" in failures or "magic" in failures


def test_copying_is_byte_for_byte() -> None:
    source = bytes(range(256))
    assert build("edge/pdf-with-png-extension.png", dependency=source) == source


# --- malformed syntax, encoding and BOM -------------------------------------


def test_the_trailing_comma_file_is_not_valid_json() -> None:
    assert check("edge/json-trailing-comma.json")["defect"] == "invalid-syntax"


def test_valid_json_under_the_trailing_comma_name_is_refused() -> None:
    clean = json.dumps({"name": "a", "count": 3}).encode()
    assert "not invalid" in refused("edge/json-trailing-comma.json", clean)


def test_the_bom_file_starts_with_a_byte_order_mark() -> None:
    data = build("edge/json-bom.json")
    assert data.startswith(b"\xef\xbb\xbf")
    assert json.loads(data.decode("utf-8-sig")) is not None
    assert check("edge/json-bom.json")["defect"] == "bom"


def test_json_without_a_bom_is_refused_under_that_name() -> None:
    assert "no byte-order mark" in refused("edge/json-bom.json", b'{"a": 1}')


def test_the_ragged_csv_has_rows_of_different_widths() -> None:
    rows = [line for line in build("edge/csv-ragged-rows.csv").decode().splitlines() if line]
    assert len({len(row.split(",")) for row in rows}) > 1
    check("edge/csv-ragged-rows.csv")


def test_a_rectangular_csv_is_refused_under_that_name() -> None:
    clean = b"id,name,city\n1,alpha,berlin\n2,beta,paris\n"
    assert "not invalid" in refused("edge/csv-ragged-rows.csv", clean)


def test_the_unclosed_xml_is_not_well_formed() -> None:
    check("edge/xml-unclosed-tag.xml")


def test_well_formed_xml_is_refused_under_that_name() -> None:
    clean = b'<?xml version="1.0" encoding="UTF-8"?>\n<catalog><item>x</item></catalog>\n'
    assert "not invalid" in refused("edge/xml-unclosed-tag.xml", clean)


def test_the_invalid_utf8_file_does_not_decode() -> None:
    data = build("edge/utf8-invalid-bytes.txt")
    with pytest.raises(UnicodeDecodeError):
        data.decode("utf-8")
    check("edge/utf8-invalid-bytes.txt")


def test_decodable_text_is_refused_under_that_name() -> None:
    assert "decodes as UTF-8" in refused("edge/utf8-invalid-bytes.txt", b"plain ascii\n")


# --- hostile archive entry --------------------------------------------------


def test_the_hostile_archive_names_an_entry_outside_the_directory() -> None:
    props = check("edge/zip-directory-traversal-name.zip")
    assert "../evil.txt" in props["hostile_entries"]


def test_a_clean_archive_is_refused_under_that_name() -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("readme.txt", "nothing hostile here")
    failures = refused("edge/zip-directory-traversal-name.zip", out.getvalue())
    assert "escapes the extraction directory" in failures


# --- determinism ------------------------------------------------------------


@pytest.mark.parametrize("path", standalone())
def test_two_builds_of_an_edge_fixture_agree(path: str) -> None:
    assert build(path) == build(path)
