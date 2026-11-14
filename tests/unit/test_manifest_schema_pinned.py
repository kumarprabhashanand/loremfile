"""The published manifest schema never changes: `src/loremfile/schema/manifest-v1.json`.

THE RULE: a new field on a manifest entry means `manifest-v2.json` and `schema_version` 2, never an
edit to v1 (docs/04 §1.4).

Why it is a test and not a convention: #153 added `aliasOf` to v1 on 2026-11-13. The document is
served with an immutable cache header and the deploy never purged it, so the edge kept the old copy,
verify-live read the difference as a hash mismatch, and, because the entry definition is
`additionalProperties: false`, any client holding the old copy rejected all 75 alias entries. A
field that readers need can be derived from fields that already exist: an alias is
`generator == "alias.copy"` and its original is `generator_params["of"]`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from loremfile import config
from loremfile.infra import purge
from loremfile.manifest import alias_original, is_alias

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "src" / "loremfile" / "schema" / "manifest-v1.json"

#: SHA-256 of the file as published in the initial release (285fda6, 2026-09-21).
PUBLISHED_SHA256 = "0b0207f133a58f099032b49105d17720a98cfdd1c35b51a9199ebd9e6542617b"
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def drifted(data: bytes) -> bool:
    """True when these bytes are not the published schema."""
    return sha256(data) != PUBLISHED_SHA256


def test_the_schema_is_the_bytes_that_were_published() -> None:
    assert not drifted(SCHEMA_PATH.read_bytes()), (
        "manifest-v1.json changed. A new entry field is manifest-v2.json and schema_version 2, "
        "never an edit to v1 (docs/04 §1.4)."
    )
    assert config.SCHEMA_VERSION == 1 and config.SCHEMA_URL.endswith("/schema/manifest-v1.json")
    assert MANIFEST["schema_version"] == 1


def test_the_pin_fires_on_the_edit_that_caused_this() -> None:
    """Control: #153's one-line addition, made again in memory, is caught; so is any other edit."""
    original = SCHEMA_PATH.read_text(encoding="utf-8")
    edited = original.replace(
        '"notes": { "type": ["string", "null"] }',
        '"notes": { "type": ["string", "null"] },\n        "aliasOf": { "$ref": "#/$defs/path" }',
    )
    assert edited != original, "control: the edit really changed the text"
    assert drifted(edited.encode()), "the aliasOf edit would pass the pin"
    assert drifted(original.encode() + b" "), "a trailing space would pass the pin"
    assert not drifted(original.encode()), "control: the real file does not trip it"


def test_v1_rejects_a_field_it_does_not_name_which_is_why_it_cannot_gain_one_quietly() -> None:
    """`additionalProperties: false` is what turned a stale copy into 75 rejected entries."""
    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    alias = next(e for e in MANIFEST["fixtures"] if e["path"] == "pdf/sample.pdf")
    validator.validate(MANIFEST)
    with pytest.raises(ValidationError, match="aliasOf"):
        validator.validate({**MANIFEST, "fixtures": [{**alias, "aliasOf": alias_original(alias)}]})


def test_no_manifest_entry_carries_an_alias_field_and_an_alias_says_what_it_is_by_generator() -> (
    None
):
    aliases = [e for e in MANIFEST["fixtures"] if is_alias(e)]
    assert len(aliases) == 77, "control: the rule finds the aliases"
    fields: set[Any] = set().union(*(e.keys() for e in MANIFEST["fixtures"]))
    assert "aliasOf" not in fields
    for entry in aliases:
        assert entry["generator"] == "alias.copy"
        original = next(e for e in MANIFEST["fixtures"] if e["path"] == alias_original(entry))
        assert original["generator"] != "alias.copy" and original["sha256"] == entry["sha256"]


def test_a_deploy_purges_the_schema_even_though_it_should_never_change() -> None:
    """The edge once held a copy that no longer matched (docs/09 §6); one operation in a batch of
    100 is cheap insurance, and the old exemption has no reader left to keep it alive."""
    _, files = purge.site_targets(["pdf"])
    assert "https://loremfile.dev/schema/manifest-v1.json" in files
    assert not hasattr(purge, "NEVER_PURGE_PREFIXES")
