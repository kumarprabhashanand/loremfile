"""M1.6 DoD: catalog schema and cross-file validation (docs/06 §3, docs/05 §1)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from catalog_helpers import minimal_fixture, minimal_format, write_format
from pydantic import ValidationError

from loremfile.catalog import Catalog, CatalogError, Fixture, FormatCatalog


def load(directory: Path) -> Catalog:
    return Catalog.load(directory)


# --- the happy path --------------------------------------------------------


def test_loads_a_valid_catalog(catalog_dir: Path) -> None:
    write_format(catalog_dir, minimal_format())
    catalog = load(catalog_dir)
    assert [f.path for f in catalog.fixtures()] == ["pdf/a4-3pages.pdf"]
    assert catalog.by_path["pdf/a4-3pages.pdf"].phase == 1


def test_empty_catalog_directory_is_valid(catalog_dir: Path) -> None:
    """Before M3 there are no catalog files; that is not an error."""
    assert list(load(catalog_dir).fixtures()) == []


def test_tags_file_is_required(tmp_path: Path) -> None:
    (tmp_path / "catalog").mkdir()
    with pytest.raises(CatalogError, match="missing tag vocabulary"):
        Catalog.load(tmp_path / "catalog")


# --- the name grammar (docs/03 §1) ----------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "a4-3pages.pdf",
        "people-1000.parquet",
        "3-text-files.tar.gz",
        "10mib-plus-1.bin",
        "640x480.png",
    ],
)
def test_valid_names(name: str) -> None:
    assert Fixture.model_validate(minimal_fixture(name=name, format="pdf")).name == name


@pytest.mark.parametrize(
    "name",
    [
        "A4-3pages.pdf",  # uppercase
        "a4_3pages.pdf",  # underscore
        "a4 3pages.pdf",  # space
        "a4-3pages",  # no extension
        "-leading.pdf",
        "trailing-.pdf",
        "double--dash.pdf",
        "sub/dir.pdf",  # only hls may nest
    ],
)
def test_invalid_names_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError, match="does not match the grammar"):
        Fixture.model_validate(minimal_fixture(name=name, format="pdf"))


@pytest.mark.parametrize(
    "name",
    ["720p-10s/index.m3u8", "multi-bitrate/master.m3u8", "720p-10s/seg-000.ts"],
)
def test_hls_nesting_is_allowed(name: str) -> None:
    assert Fixture.model_validate(minimal_fixture(name=name, format="hls")).name == name


@pytest.mark.parametrize(
    "name",
    [
        "720p-10s/playlist.m3u8",  # only index or master
        "720p-10s/seg-1.ts",  # segments are three digits
        "720p-10s/seg-0000.ts",
        "index.m3u8",  # hls always nests
    ],
)
def test_invalid_hls_names_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError, match="does not match the grammar"):
        Fixture.model_validate(minimal_fixture(name=name, format="hls"))


def test_hls_exception_does_not_leak_to_other_formats() -> None:
    with pytest.raises(ValidationError):
        Fixture.model_validate(minimal_fixture(name="720p-10s/index.m3u8", format="mp4"))


# --- ext derivation (docs/04 §1.2) ----------------------------------------


@pytest.mark.parametrize(
    ("fmt", "name", "expected"),
    [
        ("pdf", "a4-3pages.pdf", "pdf"),
        ("tar", "3-text-files.tar.gz", "tar.gz"),
        ("hls", "720p-10s/index.m3u8", "m3u8"),
        ("hls", "720p-10s/seg-000.ts", "ts"),
    ],
)
def test_ext_is_everything_after_the_first_dot_of_the_last_segment(
    fmt: str, name: str, expected: str
) -> None:
    assert Fixture.model_validate(minimal_fixture(name=name, format=fmt)).ext == expected


# --- required-field rules (docs/06 §3) ------------------------------------


def test_expect_required_unless_edge_case() -> None:
    with pytest.raises(ValidationError, match="expect is required"):
        Fixture.model_validate(minimal_fixture(format="pdf", expect=None))
    Fixture.model_validate(minimal_fixture(format="pdf", expect=None, edge_case=True))


@pytest.mark.parametrize("size_class", ["exact", "boundary", "approx"])
def test_nominal_bytes_required_for_sized_classes(size_class: str) -> None:
    with pytest.raises(ValidationError, match="nominal_bytes is required"):
        Fixture.model_validate(minimal_fixture(format="bin", size_class=size_class))
    Fixture.model_validate(minimal_fixture(format="bin", size_class=size_class, nominal_bytes=1000))


def test_nominal_bytes_rejected_for_free() -> None:
    with pytest.raises(ValidationError, match="meaningless for size_class 'free'"):
        Fixture.model_validate(minimal_fixture(format="pdf", nominal_bytes=1000))


def test_description_length_is_capped() -> None:
    with pytest.raises(ValidationError):
        Fixture.model_validate(minimal_fixture(format="pdf", description="x" * 301))


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Fixture.model_validate(minimal_fixture(format="pdf", colour="red"))


# --- edge fixtures (docs/04 §1.3) -----------------------------------------


def test_edge_fixture_needs_an_edge_block() -> None:
    with pytest.raises(ValidationError, match="needs an 'edge' block"):
        Fixture.model_validate(
            minimal_fixture(format="edge", name="truncated.png", edge_case=True, expect=None)
        )


def test_non_edge_fixture_may_not_carry_an_edge_block() -> None:
    with pytest.raises(ValidationError, match="only fixtures under edge/"):
        Fixture.model_validate(
            minimal_fixture(format="pdf", edge={"intended_format": "pdf", "defect": "zero-byte"})
        )


def test_edge_fixture_must_set_edge_case() -> None:
    with pytest.raises(ValidationError, match="must set edge_case: true"):
        Fixture.model_validate(
            minimal_fixture(
                format="edge",
                name="zero-byte.png",
                edge={"intended_format": "png", "defect": "zero-byte"},
            )
        )


def test_truncated_requires_a_fraction() -> None:
    with pytest.raises(ValidationError, match=r"edge\.fraction is required"):
        Fixture.model_validate(
            minimal_fixture(
                format="edge",
                name="pdf-truncated-60pct.pdf",
                edge_case=True,
                expect=None,
                edge={
                    "intended_format": "pdf",
                    "defect": "truncated",
                    "source_fixture": "pdf/a4-3pages.pdf",
                },
            )
        )


def test_magic_prefix_requires_magic() -> None:
    with pytest.raises(ValidationError, match=r"edge\.magic is required"):
        Fixture.model_validate(
            minimal_fixture(
                format="edge",
                name="exe-header-with-txt-extension.txt",
                edge_case=True,
                expect=None,
                edge={"intended_format": "txt", "defect": "magic-prefix"},
            )
        )


def test_defect_enum_is_closed() -> None:
    with pytest.raises(ValidationError):
        Fixture.model_validate(
            minimal_fixture(
                format="edge",
                name="weird.png",
                edge_case=True,
                expect=None,
                edge={"intended_format": "png", "defect": "slightly-off"},
            )
        )


# --- removal / tombstone rules --------------------------------------------


def test_removed_requires_a_removed_block() -> None:
    with pytest.raises(ValidationError, match="removed is required"):
        Fixture.model_validate(minimal_fixture(format="pdf", status="removed"))


def test_removed_block_rejected_while_active() -> None:
    with pytest.raises(ValidationError, match="only allowed when status is 'removed'"):
        Fixture.model_validate(
            minimal_fixture(
                format="pdf", removed={"reason": "legal", "removed_at": "2027-03-01T10:00:00Z"}
            )
        )


# --- cross-file rules ------------------------------------------------------


def test_duplicate_names_within_a_format(catalog_dir: Path) -> None:
    doc = minimal_format(fixtures=[minimal_fixture(), minimal_fixture()])
    write_format(catalog_dir, doc)
    with pytest.raises(ValidationError, match="duplicate fixture name"):
        load(catalog_dir)


def test_tags_must_come_from_the_vocabulary(catalog_dir: Path) -> None:
    write_format(catalog_dir, minimal_format(fixtures=[minimal_fixture(tags=["nonsense"])]))
    with pytest.raises(CatalogError, match=r"tags not in catalog/_tags\.yaml"):
        load(catalog_dir)


def test_related_must_name_known_formats(catalog_dir: Path) -> None:
    write_format(catalog_dir, minimal_format(related=["docx"]))
    with pytest.raises(CatalogError, match="unknown formats"):
        load(catalog_dir)


def test_related_may_not_list_itself(catalog_dir: Path) -> None:
    write_format(catalog_dir, minimal_format(related=["pdf"]))
    with pytest.raises(CatalogError, match="lists itself"):
        load(catalog_dir)


def test_filename_must_match_the_declared_format(catalog_dir: Path) -> None:
    (catalog_dir / "docx.yaml").write_text(
        yaml.safe_dump(minimal_format(), sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(CatalogError, match="declares format 'pdf'"):
        load(catalog_dir)


def test_depends_on_must_exist(catalog_dir: Path) -> None:
    write_format(
        catalog_dir, minimal_format(fixtures=[minimal_fixture(depends_on=["pdf/nope.pdf"])])
    )
    with pytest.raises(CatalogError, match="depends_on unknown path"):
        load(catalog_dir)


def test_depends_on_must_be_phase_consistent(catalog_dir: Path) -> None:
    write_format(
        catalog_dir,
        minimal_format(
            fixtures=[
                minimal_fixture(name="later.pdf", phase=2),
                minimal_fixture(name="earlier.pdf", phase=1, depends_on=["pdf/later.pdf"]),
            ]
        ),
    )
    with pytest.raises(CatalogError, match=r"phase 1\) depends on"):
        load(catalog_dir)


def test_depends_on_cycles_are_rejected(catalog_dir: Path) -> None:
    write_format(
        catalog_dir,
        minimal_format(
            fixtures=[
                minimal_fixture(name="one.pdf", depends_on=["pdf/two.pdf"]),
                minimal_fixture(name="two.pdf", depends_on=["pdf/one.pdf"]),
            ]
        ),
    )
    with pytest.raises(CatalogError, match="depends_on cycle"):
        load(catalog_dir)


def test_a_dependency_chain_is_fine(catalog_dir: Path) -> None:
    write_format(
        catalog_dir,
        minimal_format(
            fixtures=[
                minimal_fixture(name="base.pdf"),
                minimal_fixture(name="middle.pdf", depends_on=["pdf/base.pdf"]),
                minimal_fixture(name="top.pdf", depends_on=["pdf/middle.pdf"]),
            ]
        ),
    )
    assert len(list(load(catalog_dir).fixtures())) == 3


# --- charset rule (docs/05 §1 rule 7) -------------------------------------


def test_text_mime_gets_utf8_appended() -> None:
    fmt = FormatCatalog.model_validate(
        minimal_format(
            format="txt",
            mime="text/plain",
            fixtures=[minimal_fixture(name="lorem.txt", format="txt")],
        )
    )
    assert fmt.mime_for(fmt.fixtures[0]) == "text/plain; charset=utf-8"


def test_explicit_charset_is_not_doubled() -> None:
    fmt = FormatCatalog.model_validate(
        minimal_format(
            format="txt",
            mime="text/plain",
            fixtures=[
                minimal_fixture(
                    name="utf16le-bom.txt", format="txt", mime="text/plain; charset=utf-16"
                )
            ],
        )
    )
    assert fmt.mime_for(fmt.fixtures[0]) == "text/plain; charset=utf-16"


def test_binary_mime_is_left_alone() -> None:
    fmt = FormatCatalog.model_validate(minimal_format())
    assert fmt.mime_for(fmt.fixtures[0]) == "application/pdf"


# --- the real repository ---------------------------------------------------


def test_shipped_tag_vocabulary_loads() -> None:
    """catalog/_tags.yaml must stay loadable and match docs/05 §4's count."""
    catalog = Catalog.load()
    assert len(catalog.tags) == 34
    assert "dataset-people" in catalog.tags
