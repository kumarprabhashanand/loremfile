"""M1.6 DoD: the manifest lock rule, tombstones, sums and formats.json (docs/04, 06 §7).

The lock rule is the single promise this project makes to its users, so it gets the
most tests: a published path's bytes, sha256 and mime can never change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from loremfile import config
from loremfile.manifest import (
    LOCKED_FIELDS,
    TOMBSTONE_FIELDS,
    Manifest,
    ManifestError,
    make_tombstone,
    render_formats_json,
    render_sha256sums,
)

SHA_A = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
SHA_B = "0" * 64


def entry(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "path": "pdf/a4-3pages.pdf",
        "url": "https://loremfile.dev/pdf/a4-3pages.pdf",
        "format": "pdf",
        "ext": "pdf",
        "mime": "application/pdf",
        "bytes": 12345,
        "sha256": SHA_A,
        "size_class": "free",
        "phase": 1,
        "description": "A4 portrait, 3 pages of Lorem Ipsum with page numbers.",
        "tags": ["document", "multi-page"],
        "edge_case": False,
        "props": {"pages": 3},
        "generator": "pdf.basic",
        "generator_params": {"pages": 3},
        "added_in": "1.0.0",
        "status": "active",
        "deprecated": False,
        "supersededBy": None,
    }
    row.update(overrides)
    return row


def manifest_with(*entries: dict[str, Any]) -> Manifest:
    return Manifest(
        catalog_version="1.0.0",
        generated_at="2026-10-01T12:00:00Z",
        toolchain_image=f"ghcr.io/x/loremfile-toolchain@sha256:{'a' * 64}",
        entries=list(entries),
    )


# --- the lock rule ---------------------------------------------------------


def test_unchanged_entry_passes() -> None:
    manifest = manifest_with(entry())
    assert manifest.check_lock({"pdf/a4-3pages.pdf": entry()}) == []


@pytest.mark.parametrize(
    ("fieldname", "value"),
    [("sha256", SHA_B), ("bytes", 999), ("mime", "application/x-pdf")],
)
def test_changing_a_locked_field_is_a_violation(fieldname: str, value: object) -> None:
    manifest = manifest_with(entry())
    diffs = manifest.check_lock({"pdf/a4-3pages.pdf": entry(**{fieldname: value})})
    assert [d.fieldname for d in diffs] == [fieldname]
    assert "would change" in str(diffs[0])


def test_every_locked_field_is_actually_checked() -> None:
    """Guards against someone shortening LOCKED_FIELDS without noticing."""
    assert set(LOCKED_FIELDS) == {"sha256", "bytes", "mime"}
    manifest = manifest_with(entry())
    changed = entry(sha256=SHA_B, bytes=1, mime="text/plain")
    assert {d.fieldname for d in manifest.check_lock({"pdf/a4-3pages.pdf": changed})} == set(
        LOCKED_FIELDS
    )


@pytest.mark.parametrize(
    ("fieldname", "value"),
    [
        ("description", "A completely rewritten description."),
        ("tags", ["document"]),
        ("notes", "regenerates differently since pypdf 6"),
        ("generator", "pdf.basic_v2"),
        ("generator_params", {"pages": 3, "extra": True}),
        ("deprecated", True),
        ("supersededBy", "pdf/a4-3pages-v2.pdf"),
    ],
)
def test_mutable_fields_may_change(fieldname: str, value: object) -> None:
    manifest = manifest_with(entry())
    assert manifest.check_lock({"pdf/a4-3pages.pdf": entry(**{fieldname: value})}) == []


def test_a_new_path_is_not_a_violation() -> None:
    manifest = manifest_with(entry())
    assert manifest.check_lock({"pdf/new.pdf": entry(path="pdf/new.pdf")}) == []


def test_props_differing_with_identical_bytes_is_a_warning_not_a_failure() -> None:
    """A validator library measuring differently must not fail the build."""
    manifest = manifest_with(entry())
    regenerated = {"pdf/a4-3pages.pdf": entry(props={"pages": 3, "pdf_version": "1.7"})}
    assert manifest.check_lock(regenerated) == []
    warnings = manifest.props_warnings(regenerated)
    assert len(warnings) == 1
    assert "keeping the committed props" in warnings[0]


def test_props_differing_with_different_bytes_is_not_warned_about() -> None:
    """Different bytes is already a lock violation; no second complaint about props."""
    manifest = manifest_with(entry())
    regenerated = {"pdf/a4-3pages.pdf": entry(sha256=SHA_B, props={"pages": 4})}
    assert manifest.props_warnings(regenerated) == []
    assert manifest.check_lock(regenerated)


# --- removals and tombstones ----------------------------------------------


def test_a_path_missing_from_the_catalog_is_an_error() -> None:
    manifest = manifest_with(entry())
    errors = manifest.check_removals(set(), {})
    assert len(errors) == 1
    assert "never dropped" in errors[0]


def test_a_path_marked_removed_in_the_catalog_is_allowed() -> None:
    manifest = manifest_with(entry())
    removable = {"pdf/a4-3pages.pdf": {"reason": "legal", "removed_at": "2027-03-01T10:00:00Z"}}
    assert manifest.check_removals(set(), removable) == []


def test_an_existing_tombstone_is_not_re_reported() -> None:
    tombstone = make_tombstone(entry(), "Legal request #12", "2027-03-01T10:00:00Z")
    assert manifest_with(tombstone).check_removals(set(), {}) == []


def test_tombstone_has_exactly_the_specified_fields() -> None:
    tombstone = make_tombstone(entry(), "Legal request #12", "2027-03-01T10:00:00Z")
    assert set(tombstone) == set(TOMBSTONE_FIELDS)
    assert "url" not in tombstone, "clients iterating url must skip removed entries"
    assert tombstone["status"] == "removed"
    assert tombstone["reason"] == "Legal request #12"
    # sha256 and bytes stay so archives can still be verified.
    assert tombstone["sha256"] == SHA_A
    assert tombstone["bytes"] == 12345


def test_tombstoning_an_incomplete_entry_fails_loudly() -> None:
    with pytest.raises(ManifestError, match="cannot tombstone"):
        make_tombstone({"path": "pdf/x.pdf"}, "reason", "2027-03-01T10:00:00Z")


# --- totals ----------------------------------------------------------------


def test_total_bytes_limit_is_enforced() -> None:
    huge = entry(bytes=config.MAX_TOTAL_BYTES + 1)
    assert manifest_with(huge).check_total_bytes()
    assert manifest_with(entry()).check_total_bytes() == []


def test_tombstones_do_not_count_towards_totals_or_counts() -> None:
    tombstone = make_tombstone(entry(path="pdf/gone.pdf"), "Legal request", "2027-03-01T10:00:00Z")
    manifest = manifest_with(entry(), tombstone)
    document = manifest.to_document()
    assert document["count"] == 1
    assert document["total_bytes"] == 12345


# --- serialisation ---------------------------------------------------------


def test_document_is_sorted_by_path_and_lists_formats() -> None:
    manifest = manifest_with(
        entry(path="png/b.png", format="png", ext="png", mime="image/png"),
        entry(path="pdf/a.pdf"),
    )
    document = manifest.to_document()
    assert [e["path"] for e in document["fixtures"]] == ["pdf/a.pdf", "png/b.png"]
    assert document["formats"] == ["pdf", "png"]


def test_serialisation_is_canonical() -> None:
    text = manifest_with(entry()).dumps()
    assert text.endswith("\n")
    assert "\r" not in text
    assert '\n  "schema_version": 1,' in text, "2-space indent"


def test_non_ascii_is_kept_literal() -> None:
    text = manifest_with(entry(description="Grüße, naïve café")).dumps()
    assert "Grüße, naïve café" in text
    assert "\\u" not in text


def test_round_trip_through_disk(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest_with(entry()).save(path)
    reloaded = Manifest.load(path)
    assert reloaded.by_path["pdf/a4-3pages.pdf"]["sha256"] == SHA_A
    assert reloaded.catalog_version == "1.0.0"


def test_missing_manifest_loads_as_empty(tmp_path: Path) -> None:
    assert Manifest.load(tmp_path / "nope.json").entries == []


def test_invalid_json_is_reported_clearly(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError, match="not valid JSON"):
        Manifest.load(path)


def test_generated_at_only_moves_when_something_changed() -> None:
    manifest = manifest_with(entry())
    before = manifest.generated_at
    manifest.touch(changed=False)
    assert manifest.generated_at == before, "an unchanged rebuild must produce no diff"
    manifest.touch(changed=True)
    assert manifest.generated_at != before


def test_touch_records_the_toolchain_image() -> None:
    manifest = manifest_with(entry())
    manifest.touch(changed=False)
    assert manifest.toolchain_image == config.toolchain_digest()
    assert "@sha256:" in manifest.toolchain_image


# --- sha256sums.txt (docs/04 §2) ------------------------------------------


def test_sha256sums_format() -> None:
    text = render_sha256sums(manifest_with(entry()))
    assert text == f"{SHA_A}  pdf/a4-3pages.pdf\n"
    assert "  " in text, "two spaces between hash and path"


def test_sha256sums_is_sorted_and_active_only() -> None:
    tombstone = make_tombstone(entry(path="pdf/gone.pdf"), "Legal request", "2027-03-01T10:00:00Z")
    manifest = manifest_with(
        entry(path="png/b.png", format="png"), entry(path="pdf/a.pdf"), tombstone
    )
    paths = [line.split("  ", 1)[1] for line in render_sha256sums(manifest).splitlines()]
    assert paths == ["pdf/a.pdf", "png/b.png"]


def test_sha256sums_ends_with_a_newline_and_has_no_bom() -> None:
    text = render_sha256sums(manifest_with(entry()))
    assert text.endswith("\n")
    assert not text.startswith("﻿")


# --- formats.json (docs/04 §3) --------------------------------------------


def test_formats_json_aggregates_per_format() -> None:
    manifest = manifest_with(
        entry(path="pdf/a.pdf", bytes=100),
        entry(path="pdf/b.pdf", bytes=200),
        entry(path="png/c.png", format="png", bytes=50, mime="image/png"),
    )
    document = json.loads(
        render_formats_json(manifest, {"pdf": "application/pdf", "png": "image/png"})
    )
    rows = {row["format"]: row for row in document["formats"]}
    assert rows["pdf"]["count"] == 2
    assert rows["pdf"]["total_bytes"] == 300
    assert rows["pdf"]["mime_default"] == "application/pdf"
    assert rows["png"]["url"] == "https://loremfile.dev/png"
    assert rows["png"]["index"] == "https://loremfile.dev/png/index.json"


def test_formats_json_excludes_tombstones() -> None:
    tombstone = make_tombstone(entry(path="pdf/gone.pdf"), "Legal request", "2027-03-01T10:00:00Z")
    document = json.loads(render_formats_json(manifest_with(tombstone), {}))
    assert document["formats"] == []


# --- the JSON Schema (docs/04 §1.4) ---------------------------------------


def schema() -> dict[str, Any]:
    path = Path(config.__file__).parent / "schema" / "manifest-v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_schema_is_itself_valid() -> None:
    Draft202012Validator.check_schema(schema())


def test_a_generated_manifest_validates() -> None:
    document = manifest_with(entry()).to_document()
    Draft202012Validator(schema()).validate(document)


def test_a_manifest_with_a_tombstone_validates() -> None:
    tombstone = make_tombstone(
        entry(path="pdf/gone.pdf"), "Legal request #12", "2027-03-01T10:00:00Z"
    )
    document = manifest_with(entry(), tombstone).to_document()
    Draft202012Validator(schema()).validate(document)


def test_schema_rejects_an_unknown_field() -> None:
    document = manifest_with(entry(surprise="yes")).to_document()
    assert list(Draft202012Validator(schema()).iter_errors(document)), (
        "additionalProperties: false must catch drift"
    )


def test_schema_rejects_a_bad_sha256() -> None:
    document = manifest_with(entry(sha256="nope")).to_document()
    assert list(Draft202012Validator(schema()).iter_errors(document))


def test_schema_rejects_a_tombstone_carrying_a_url() -> None:
    tombstone = make_tombstone(entry(path="pdf/gone.pdf"), "Legal request", "2027-03-01T10:00:00Z")
    tombstone["url"] = "https://loremfile.dev/pdf/gone.pdf"
    document = manifest_with(tombstone).to_document()
    assert list(Draft202012Validator(schema()).iter_errors(document))


def test_schema_rejects_a_fixture_over_the_size_cap() -> None:
    document = manifest_with(entry(bytes=config.MAX_FIXTURE_BYTES + 1)).to_document()
    assert list(Draft202012Validator(schema()).iter_errors(document))


# --- the committed manifest, once one exists ------------------------------


def test_committed_manifest_validates_if_present() -> None:
    path = config.manifest_path()
    if not path.is_file():
        pytest.skip("no manifest.json yet; the first fixtures arrive in M3")
    document = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(schema()).validate(document)
