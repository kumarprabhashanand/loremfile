"""The four props that describe a broken file: what is wrong with it, what it was cut
from, what to compare it against, and what it does to a reader (docs/04 §1.3).

None of the four is written by hand. ``derived_from`` is measured against the source's
own bytes, ``compare_with`` is cross-checked in the catalog, ``damage`` is a sentence
composed out of what the validator measured, and ``outcome`` is derived from two
readings of the file and required to equal the value the catalog declares.

So every test here is one of two things: it drives a derivation and reads the result, or
it is the negative control that the check fires — because a check that cannot fail about
a file that is deliberately broken is indistinguishable from no check at all.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from catalog_helpers import minimal_edge, minimal_fixture, minimal_format, write_format

from loremfile.catalog import Catalog, CatalogError, Defect, Fixture, Outcome
from loremfile.validators import ValidationError, validate
from loremfile.validators import edge as edge_validator
from loremfile.validators import load as load_validators

load_validators()

CATALOG = Catalog.load()
ROOT = Path(__file__).resolve().parents[2]
EDGE = [f for f in CATALOG.fixtures() if f.format == "edge"]

#: A PDF the size of a real one, cut where the catalog says. Built here rather than read
#: from `build/fixtures/`, because a unit test that needs a build is a test that is
#: skipped on the machine where it would have caught something.
PDF_OBJECT = b"1 0 obj\n<< /Type /Page >>\nendobj\n"
WHOLE_PDF = b"%PDF-1.7\n" + PDF_OBJECT * 8 + b"xref\n0 1\ntrailer\nstartxref\n9\n%%EOF\n"


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    supplied: dict[str, bytes] = {}
    monkeypatch.setattr(edge_validator, "SOURCE_READER", supplied.__getitem__)
    return supplied


def entry(path: str) -> Fixture:
    return CATALOG.by_path[path]


def run(fixture: Fixture, data: bytes) -> dict[str, Any]:
    report = validate(data, fixture, CATALOG.mime_for(fixture))
    assert report.ok, report.failures
    return report.props


def refused(fixture: Fixture, data: bytes) -> str:
    report = validate(data, fixture, CATALOG.mime_for(fixture))
    assert not report.ok, f"{fixture.path} accepted bytes it should have refused"
    return " | ".join(report.failures)


def subject(fixture: Fixture, data: bytes) -> edge_validator.Subject:
    assert fixture.edge is not None
    return edge_validator.Subject(
        data=data, fixture=fixture, edge=fixture.edge, mime=CATALOG.mime_for(fixture)
    )


# --- the set these tests are quantified over --------------------------------------------


def test_the_edge_set_is_the_files_these_tests_think_it_is() -> None:
    """The control for every "for each edge fixture" below: a renamed directory or a
    changed format name would otherwise leave them all true of nothing."""
    paths = {fixture.path for fixture in EDGE}
    assert {
        "edge/zero-byte.pdf",
        "edge/pdf-truncated-60pct.pdf",
        "edge/png-with-pdf-extension.pdf",
        "edge/json-bom.json",
        "edge/zip-directory-traversal-name.zip",
    } <= paths


def test_every_edge_fixture_names_a_comparison_and_an_outcome() -> None:
    for fixture in EDGE:
        assert fixture.edge is not None
        assert fixture.edge.compare_with in CATALOG.by_path, fixture.path
        assert fixture.edge.outcome in set(Outcome), fixture.path


def test_only_the_derived_fixtures_claim_a_parent() -> None:
    """Six of the nineteen are cut or copied from a published file; the other thirteen
    are generated whole and have no parent to name."""
    derived = {fixture.path for fixture in EDGE if fixture.edge and fixture.edge.source_fixture}
    assert derived == {
        "edge/pdf-truncated-60pct.pdf",
        "edge/jpg-truncated-50pct.jpg",
        "edge/mp4-truncated-50pct.mp4",
        "edge/zip-truncated-50pct.zip",
        "edge/png-with-pdf-extension.pdf",
        "edge/pdf-with-png-extension.png",
    }
    for fixture in EDGE:
        assert fixture.edge is not None
        if fixture.edge.source_fixture is None:
            continue
        assert fixture.edge.source_fixture == fixture.params["source"], fixture.path


# --- derived_from: measured against the source's own bytes ------------------------------


def test_a_truncation_is_measured_against_the_bytes_it_was_cut_from(
    sources: dict[str, bytes],
) -> None:
    fixture = entry("edge/pdf-truncated-60pct.pdf")
    sources["pdf/a4-3pages.pdf"] = WHOLE_PDF
    props = run(fixture, WHOLE_PDF[: int(len(WHOLE_PDF) * 0.6)])

    assert props["derived_from"] == "pdf/a4-3pages.pdf"
    assert f"of {len(WHOLE_PDF):,} bytes" in props["damage"]
    assert "the first 60% of pdf/a4-3pages.pdf" in props["damage"]


def test_a_truncation_of_the_wrong_length_is_refused(sources: dict[str, bytes]) -> None:
    """The negative control for the arithmetic: one byte too many is not 60%."""
    fixture = entry("edge/pdf-truncated-60pct.pdf")
    sources["pdf/a4-3pages.pdf"] = WHOLE_PDF
    cut = int(len(WHOLE_PDF) * 0.6)
    failures = refused(fixture, WHOLE_PDF[: cut + 1])
    assert f"holds {cut + 1:,} bytes" in failures
    assert f"is {cut:,}" in failures


def test_a_truncation_that_is_not_a_prefix_is_refused(sources: dict[str, bytes]) -> None:
    fixture = entry("edge/pdf-truncated-60pct.pdf")
    sources["pdf/a4-3pages.pdf"] = WHOLE_PDF
    cut = int(len(WHOLE_PDF) * 0.6)
    altered = b"%PDF-1.7\n" + bytes(cut - 9)
    assert "is not a prefix of pdf/a4-3pages.pdf" in refused(fixture, altered)


def test_a_copy_that_differs_from_its_parent_is_refused(sources: dict[str, bytes]) -> None:
    fixture = entry("edge/pdf-with-png-extension.png")
    sources["pdf/a4-1page.pdf"] = WHOLE_PDF
    assert "is not pdf/a4-1page.pdf byte for byte" in refused(fixture, WHOLE_PDF + b"\n")


def test_a_parent_that_is_not_on_disk_stops_the_check_rather_than_passing() -> None:
    """Reading the source is how `derived_from` is more than a repeated string. If the
    file is not there the check cannot run, and a check that cannot run must not pass."""
    with pytest.raises(ValidationError, match="not in build/fixtures"):
        edge_validator.read_source("pdf/no-such-fixture.pdf")


# --- compare_with: cross-checked where the paths are ------------------------------------


def edge_catalog(**edge: Any) -> list[dict[str, Any]]:
    """A throwaway catalog: one valid pdf, one png, and one edge case pointing at them."""
    return [
        minimal_fixture(name="a4-3pages.pdf"),
        minimal_fixture(
            name="zero-byte.pdf",
            format="edge",
            generator="edge.zero_byte",
            params={},
            expect=None,
            edge_case=True,
            tags=["invalid"],
            edge=minimal_edge(**edge),
        ),
    ]


def load_with(catalog_dir: Path, **edge: Any) -> Catalog:
    write_format(catalog_dir, minimal_format(fixtures=edge_catalog(**edge)))
    return Catalog.load(catalog_dir)


def test_a_comparison_that_names_a_real_fixture_loads(catalog_dir: Path) -> None:
    """The control: the three refusals below are refusals, not a catalog that never loads."""
    catalog = load_with(catalog_dir, compare_with="pdf/a4-3pages.pdf")
    assert catalog.by_path["edge/zero-byte.pdf"].edge.compare_with == "pdf/a4-3pages.pdf"


def test_a_comparison_with_an_unknown_path_is_refused(catalog_dir: Path) -> None:
    with pytest.raises(CatalogError, match="compare_with unknown path"):
        load_with(catalog_dir, compare_with="pdf/not-published.pdf")


def test_a_comparison_of_the_wrong_type_is_refused(catalog_dir: Path) -> None:
    """`zero-byte.pdf` announces itself as a pdf, so a valid png proves nothing about
    the reader that refused it."""
    write_format(
        catalog_dir,
        minimal_format(
            format="png",
            mime="image/png",
            fixtures=[minimal_fixture(format="png", name="100x100.png", tags=["image"])],
        ),
    )
    with pytest.raises(CatalogError, match=r"\(format png\), but this one announces itself as pdf"):
        load_with(catalog_dir, compare_with="png/100x100.png")


def test_a_comparison_with_another_broken_file_is_refused(catalog_dir: Path) -> None:
    """A second odd file tells a reader nothing: the comparison has to be the good one.
    The target here is a pdf, so it is the right type and still the wrong file."""
    fixtures = edge_catalog(compare_with="pdf/control-characters.pdf")
    fixtures.insert(1, minimal_fixture(name="control-characters.pdf", edge_case=True))
    write_format(catalog_dir, minimal_format(fixtures=fixtures))
    with pytest.raises(CatalogError, match="must name a valid, active fixture"):
        Catalog.load(catalog_dir)


def test_a_file_cut_from_a_twin_must_compare_with_that_twin(catalog_dir: Path) -> None:
    """A truncation has an obvious comparison — the file it was cut from — and naming a
    different one hides the only pair a reader can be tested on."""
    fixtures = edge_catalog(
        defect="truncated",
        fraction=0.6,
        source_fixture="pdf/a4-3pages.pdf",
        compare_with="pdf/other.pdf",
        outcome="may-recover",
    )
    fixtures.insert(1, minimal_fixture(name="other.pdf"))
    fixtures[2]["depends_on"] = ["pdf/a4-3pages.pdf"]
    write_format(catalog_dir, minimal_format(fixtures=fixtures))
    with pytest.raises(CatalogError, match="which is the file to compare with"):
        Catalog.load(catalog_dir)


def test_every_comparison_names_a_file_that_is_published_and_active() -> None:
    """The claim the prop makes to a reader: this one is a good file of the same type.
    It holds because an entry only reaches the manifest once its validator measured it,
    so the check that matters here is that the path is really in there."""
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    active = {
        entry["path"] for entry in manifest["fixtures"] if entry.get("status", "active") == "active"
    }
    assert "pdf/minimal.pdf" in active, "control: the manifest was read and holds fixtures"
    for fixture in EDGE:
        assert fixture.edge is not None
        assert fixture.edge.compare_with in active, fixture.path


# --- damage: every sentence has to be refusable ------------------------------------------


def test_a_truncated_pdf_that_still_has_its_trailer_is_refused(sources: dict[str, bytes]) -> None:
    """The sentence says the cross-reference table is past the end. If it is not, the
    sentence is wrong, and a wrong sentence must not be published."""
    fixture = entry("edge/pdf-truncated-60pct.pdf")
    whole = b"%PDF-1.7\n" + PDF_OBJECT * 4 + b"startxref\n9\n%%EOF\n" + bytes(200)
    sources["pdf/a4-3pages.pdf"] = whole
    assert "startxref or %%EOF" in refused(fixture, whole[: int(len(whole) * 0.6)])


def test_a_truncated_jpg_that_ends_with_its_marker_is_refused(sources: dict[str, bytes]) -> None:
    fixture = entry("edge/jpg-truncated-50pct.jpg")
    whole = b"\xff\xd8\xff" + bytes(100) + b"\xff\xd9" + bytes(105)
    sources["jpg/640x480.jpg"] = whole
    assert "end-of-image marker" in refused(fixture, whole[: len(whole) // 2])


def test_a_truncated_zip_that_still_has_its_directory_is_refused(
    sources: dict[str, bytes],
) -> None:
    fixture = entry("edge/zip-truncated-50pct.zip")
    # An end-of-central-directory signature with too few bytes after it: zipfile
    # refuses the archive, so the defect check passes it on, and the marker the
    # sentence claims is missing is right there.
    half = b"PK\x03\x04" + bytes(26) + b"PK\x05\x06" + bytes(4)
    sources["zip/3-text-files.zip"] = half + bytes(len(half))
    assert "end-of-central-directory" in refused(fixture, half)


def test_a_truncated_mp4_whose_boxes_all_fit_is_refused(sources: dict[str, bytes]) -> None:
    """ffprobe reads a cut MP4 without complaint, so the box table is what says it is
    short. A file whose boxes all fit is not cut, whatever its length."""
    box = (16).to_bytes(4, "big") + b"ftyp" + bytes(8)
    sources["mp4/720p-5s.mp4"] = box * 2
    assert "not cut short" in refused(entry("edge/mp4-truncated-50pct.mp4"), box)


def test_the_json_sentence_needs_a_comma_before_a_bracket() -> None:
    """Invalid JSON is not enough: the sentence names a trailing comma, so there has to
    be one. Driven directly, because the defect check refuses these bytes first."""
    fixture = entry("edge/json-trailing-comma.json")
    with pytest.raises(ValidationError, match="not for a comma before a closing bracket"):
        edge_validator.DAMAGE[fixture.edge.defect](subject(fixture, b'{"a": }'))


def test_the_csv_sentence_needs_rows_of_different_widths() -> None:
    fixture = entry("edge/csv-ragged-rows.csv")
    with pytest.raises(ValidationError, match="fields in every row"):
        edge_validator.DAMAGE[fixture.edge.defect](subject(fixture, b"a,b\n1,2\n"))


def test_the_xml_sentence_needs_an_element_that_is_never_closed() -> None:
    fixture = entry("edge/xml-unclosed-tag.xml")
    with pytest.raises(ValidationError, match="every element it opens is closed"):
        edge_validator.DAMAGE[fixture.edge.defect](subject(fixture, b"<a></a><b></b>"))


def test_the_bom_sentence_needs_what_follows_the_mark_to_be_valid() -> None:
    """It says "an otherwise valid document". If the rest is broken too, the sentence is
    about the wrong problem, and the fixture is the wrong fixture."""
    fixture = entry("edge/json-bom.json")
    assert fixture.edge is not None
    with pytest.raises(ValidationError, match="not valid json once the mark is removed"):
        edge_validator.DAMAGE[fixture.edge.defect](subject(fixture, b'\xef\xbb\xbf{"a": '))


def test_a_format_with_no_sentence_for_an_empty_file_is_refused() -> None:
    """The gap is the point: adding an edge case for a new format without saying what
    that format's reader looks for first stops the build rather than publishing "it is
    empty", which says nothing."""
    fixture = Fixture.model_validate(
        minimal_fixture(
            name="zero-byte.ics",
            format="edge",
            generator="edge.zero_byte",
            params={},
            expect=None,
            edge_case=True,
            tags=["invalid"],
            edge=minimal_edge(intended_format="ics", compare_with="ics/one-event.ics"),
        )
    )
    report = validate(b"", fixture, "text/calendar; charset=utf-8")
    assert any("looks for first" in failure for failure in report.failures), report.failures


# --- outcome: derived from the bytes, and required to match the catalog -------------------


def test_the_bytes_overrule_the_catalog(sources: dict[str, bytes]) -> None:
    """The one assertion that makes `outcome` worth publishing: a value nobody checked
    is a value that drifts. Here the file really is recoverable and the catalog says it
    must fail, and the fixture is refused."""
    fixture = entry("edge/pdf-truncated-60pct.pdf")
    wrong = fixture.model_copy(
        update={"edge": fixture.edge.model_copy(update={"outcome": Outcome.MUST_FAIL})}
    )
    sources["pdf/a4-3pages.pdf"] = WHOLE_PDF
    failures = refused(wrong, WHOLE_PDF[: int(len(WHOLE_PDF) * 0.6)])
    assert "declares outcome 'must-fail' and the bytes say 'may-recover'" in failures


TRUNCATED = [f for f in EDGE if f.edge is not None and f.edge.defect is Defect.TRUNCATED]


@pytest.mark.parametrize("fixture", TRUNCATED, ids=lambda f: f.path)
def test_a_truncated_file_is_never_varies_whatever_a_reader_says(
    monkeypatch: pytest.MonkeyPatch, fixture: Fixture
) -> None:
    """Bytes are missing, so nothing gets the whole file — and `varies` means something
    does. This is about the order of the branches, not about any one format: both
    readings are made to claim the file entire, and the answer still may not be `varies`.

    ffprobe reads a truncated MP4 without complaint, so mp4 is the format that found
    this. The rule is the one the next truncated fixture needs.
    """
    assert {"edge/pdf-truncated-60pct.pdf", "edge/mp4-truncated-50pct.mp4"} <= {
        f.path for f in TRUNCATED
    }, "control: the truncated fixtures were found"
    assert fixture.edge is not None
    monkeypatch.setattr(edge_validator.Subject, "accepts", lambda *_args: True)
    monkeypatch.setitem(
        edge_validator.RECOVERIES,
        fixture.ext,
        lambda _data: edge_validator.Recovery(whole=True, evidence="all of it, allegedly"),
    )
    outcome, _why = edge_validator.derive_outcome(subject(fixture, b"whatever arrived"))
    assert outcome is not Outcome.VARIES
    assert fixture.edge.outcome is not Outcome.VARIES, "and the catalog says so too"


def test_nothing_readable_is_must_fail() -> None:
    outcome, why = edge_validator.derive_outcome(subject(entry("edge/zero-byte.json"), b""))
    assert outcome is Outcome.MUST_FAIL
    assert why == "no conforming reader gets anything out of it"


def test_part_of_the_content_is_may_recover() -> None:
    fixture = entry("edge/utf8-invalid-bytes.txt")
    outcome, why = edge_validator.derive_outcome(subject(fixture, b"before \xc3\x28 after\n"))
    assert outcome is Outcome.MAY_RECOVER
    assert "replaced by U+FFFD" in why


def test_a_reader_that_takes_it_whole_is_varies() -> None:
    fixture = entry("edge/json-bom.json")
    outcome, why = edge_validator.derive_outcome(subject(fixture, b'\xef\xbb\xbf{"a": 1}'))
    assert outcome is Outcome.VARIES
    assert "byte-order mark is skipped" in why


def test_a_format_with_no_tolerant_reading_stops_the_check() -> None:
    """`must-fail` would otherwise be the answer for every format nobody has thought
    about — the most confident of the three values, reached by not looking."""
    fixture = entry("edge/zero-byte.json")
    posing = fixture.model_copy(update={"name": "zero-byte.yaml"})
    with pytest.raises(ValidationError, match="no tolerant reading defined for yaml"):
        edge_validator.derive_outcome(subject(posing, b"{oh: [no"))


def test_a_format_with_no_reader_at_all_stops_the_check() -> None:
    """A "no" from a reader that was never run is the shape of check that passes on
    absence, so `accepts` refuses to answer instead of returning False."""
    fixture = entry("edge/zero-byte.json")
    with pytest.raises(ValidationError, match="no validator is registered"):
        subject(fixture, b"").accepts("not-a-format")


def test_the_archive_sentence_names_the_entry_that_escapes() -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("readme.txt", "ordinary")
        archive.writestr("../evil.txt", "not ordinary")
    props = run(entry("edge/zip-directory-traversal-name.zip"), out.getvalue())
    assert "entry 2 of 2 is named '../evil.txt'" in props["damage"]
    assert props["outcome"] == "varies"
    assert props["hostile_entries"] == ["../evil.txt"]
