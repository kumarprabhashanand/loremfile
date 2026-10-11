"""`props.contains_text`: from the generator's input, found by a real reader (docs/04 §1.3.2).

CI builds only the fixtures a pull request adds, so nothing else would ever regenerate the
published files that carry these strings. This module does: it records each one's
generator input, confirms the bytes are the published ones, and checks every string.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from catalog_helpers import minimal_fixture
from pydantic import ValidationError

from loremfile import build, contains
from loremfile.catalog import Catalog, Fixture
from loremfile.cli import _catalog_disagreements
from loremfile.manifest import Manifest
from loremfile.util import lorem
from loremfile.validators import extract, load, validate

CATALOG = Catalog.load()
MANIFEST = Manifest.load()
CONTAINING = sorted(f.path for f in CATALOG.fixtures() if f.contains_text)
build.load_generators()
load()


def strings(path: str) -> list[str]:
    return CATALOG.by_path[path].contains_text or []


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> dict[str, contains.Recorded]:
    work = tmp_path_factory.mktemp("contains")
    cache: dict[str, bytes] = {}

    def resolve(path: str) -> bytes:
        if path not in cache:
            cache[path] = build.generate_one(CATALOG.by_path[path], work, resolve).data
        return cache[path]

    return {path: contains.record(CATALOG.by_path[path], work, resolve) for path in CONTAINING}


@pytest.fixture(scope="module")
def texts(recorded: dict[str, contains.Recorded]) -> dict[str, str]:
    return {
        path: extract.text(
            CATALOG.by_path[path].format,
            item.data,
            password=CATALOG.by_path[path].params.get("user_password"),
        )
        for path, item in recorded.items()
    }


def shared_with(path: str, texts: dict[str, str], candidate: list[str]) -> list[str]:
    """The other files of this format that hold every one of ``candidate``."""
    fmt = path.split("/", 1)[0]
    return [
        other
        for other, text in texts.items()
        if other != path
        and other.startswith(f"{fmt}/")
        and all(string in text for string in candidate)
    ]


def test_the_chosen_fixtures_carry_it() -> None:
    """Empty-set control: every check below is a loop over CONTAINING."""
    assert {
        "pdf/a4-10pages.pdf",
        "pdf/a4-encrypted-1page.pdf",
        "docx/with-tracked-changes.docx",
        "pptx/10slides.pptx",
        "xlsx/1sheet-1000rows.xlsx",
        "epub/epub3-3chapters.epub",
        "html/basic.html",
        "md/all-elements.md",
    } <= set(CONTAINING)


def test_what_was_recorded_is_the_published_file(recorded: dict[str, contains.Recorded]) -> None:
    published = MANIFEST.by_path
    assert {path: item.sha256 for path, item in recorded.items()} == {
        path: published[path]["sha256"] for path in CONTAINING
    }


@pytest.mark.parametrize("path", CONTAINING)
def test_every_string_comes_from_the_generators_input(
    recorded: dict[str, contains.Recorded], path: str
) -> None:
    assert [s for s in strings(path) if not recorded[path].supplies(s)] == []


@pytest.mark.parametrize("path", CONTAINING)
def test_a_real_reader_finds_every_string(texts: dict[str, str], path: str) -> None:
    assert [s for s in strings(path) if s not in texts[path]] == []


@pytest.mark.parametrize("path", CONTAINING)
def test_the_strings_fail_every_other_file_of_the_format(texts: dict[str, str], path: str) -> None:
    assert shared_with(path, texts, strings(path)) == []


def test_the_manifest_publishes_exactly_the_catalogs_strings() -> None:
    published = {
        entry["path"]: entry["props"]["contains_text"]
        for entry in MANIFEST.active
        if "contains_text" in (entry.get("props") or {})
    }
    assert published == {path: strings(path) for path in CONTAINING}


# --- controls: each check above, watched failing ----------------------------------------


def test_the_input_check_refuses_text_the_generator_never_wrote(
    recorded: dict[str, contains.Recorded],
) -> None:
    item = recorded["docx/1page.docx"]
    assert item.supplies(strings("docx/1page.docx")[0])
    assert not item.supplies("Quantum harmonica zebra")
    assert not item.supplies(strings("pdf/a4-1page.pdf")[0]), "another fixture's draw"


def test_the_reader_check_refuses_text_the_reader_does_not_return(
    recorded: dict[str, contains.Recorded], texts: dict[str, str]
) -> None:
    """The deleted word is in the generator's input and in the XML, not in the text."""
    path = "docx/with-tracked-changes.docx"
    assert recorded[path].supplies("cancelled")
    assert "cancelled" not in texts[path]
    fixture = CATALOG.by_path[path]
    bad = fixture.model_copy(update={"contains_text": [*strings(path), "cancelled"]})
    mime = CATALOG.mime_for(fixture)
    report = validate(recorded[path].data, bad, mime)
    assert any("does not find: ['cancelled']" in failure for failure in report.failures)
    assert "contains_text" not in report.props
    assert validate(recorded[path].data, fixture, mime).props["contains_text"] == strings(path)


def test_the_distinctness_check_names_a_file_that_holds_them_all(
    texts: dict[str, str],
) -> None:
    """Every one-page lorem PDF opens with the same heading, so that heading cannot tell
    them apart, and the check says which files it fails to tell apart."""
    heading = ["loremfile.dev - page 1 of 1"]
    assert "pdf/letter-1page.pdf" in shared_with("pdf/a4-1page.pdf", texts, heading)


def test_a_format_without_a_reader_cannot_carry_it() -> None:
    fixture = CATALOG.by_path["rtf/simple.rtf"]
    bad = fixture.model_copy(update={"contains_text": ["a", "b", "c"]})
    report = validate(b"{\\rtf1}", bad, CATALOG.mime_for(fixture))
    assert any("rtf has none" in failure for failure in report.failures)


def test_manifest_check_names_a_catalog_edit_that_was_not_rebuilt() -> None:
    catalog = Catalog.load()
    assert _catalog_disagreements(MANIFEST, catalog) == []
    edited = ["edited, never rebuilt", "x" * 9, "y" * 9]
    catalog.by_path["md/all-elements.md"].contains_text = edited
    assert [e.split(":")[0] for e in _catalog_disagreements(MANIFEST, catalog)] == [
        "md/all-elements.md"
    ]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (["Rerum repellat quia elit", "Saepe enim eu placeat"], "at least 3"),
        (["Lorem", "Saepe enim eu placeat", "Omnis quia neque elit"], "under 8 characters"),
        (["Saepe enim eu placeat"] * 3, "repeats a string"),
        (["Saepe  enim eu placeat", "Rerum repellat", "Omnis quia neque"], "untidy whitespace"),
    ],
)
def test_the_catalog_refuses_strings_too_weak_to_fail_a_wrong_file(
    value: list[str], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Fixture(**minimal_fixture(contains_text=value), format="pdf")


def test_recording_leaves_the_lorem_module_as_it_found_it(tmp_path: Path) -> None:
    before = lorem.paragraph
    contains.record(CATALOG.by_path["html/basic.html"], tmp_path)
    assert lorem.paragraph is before


def test_manifest_check_names_a_supersession_the_catalog_has_not_published() -> None:
    catalog = Catalog.load()
    catalog.by_path["jpg/cmyk-640x480.jpg"].superseded_by = None
    assert [e.split(":")[0] for e in _catalog_disagreements(MANIFEST, catalog)] == [
        "jpg/cmyk-640x480.jpg"
    ]
