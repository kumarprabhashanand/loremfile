"""M4.4: the deploy's bucket side, and the arithmetic the launch set has to keep.

`r2.py` is the only place that talks to R2, so these run it against a fake client. What
is being tested is not boto3 — it is that the deploy asks the bucket the right questions:
a listing before any HEAD, a HEAD for the metadata a listing cannot return, and a refusal
rather than a guess when the metadata is not there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from loremfile import build as build_module
from loremfile.build import BuildError, Selection
from loremfile.catalog import Catalog
from loremfile.infra import locks, r2

CATALOG = Catalog.load()


def nothing_published() -> set[str]:
    """A bucket with nothing in it — the state of a first deploy."""
    return set()


class FakeBucket:
    """Enough of the S3 API for the deploy's read path, and a record of what was asked."""

    def __init__(self, objects: dict[str, dict[str, str]], *, page: int = 1000) -> None:
        self.objects = objects
        self.page = page
        self.heads: list[str] = []
        self.lists = 0

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        self.lists += 1
        keys = sorted(self.objects)
        prefix = kwargs.get("Prefix", "")
        if prefix:
            keys = [k for k in keys if k.startswith(prefix)]
        start = keys.index(kwargs["ContinuationToken"]) if kwargs.get("ContinuationToken") else 0
        window = keys[start : start + self.page]
        truncated = start + self.page < len(keys)
        return {
            "Contents": [{"Key": key} for key in window],
            "IsTruncated": truncated,
            "NextContinuationToken": keys[start + self.page] if truncated else None,
        }

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.heads.append(kwargs["Key"])
        return {"Metadata": dict(self.objects[kwargs["Key"]])}


def test_the_listing_is_paginated_rather_than_truncated_at_a_thousand() -> None:
    """A silently truncated listing would make published keys look absent and be
    re-uploaded — into a locked prefix, where the write is refused and the deploy fails
    for a reason that names the lock rather than the pagination."""
    bucket = FakeBucket({f"bin/{n:04d}.bin": {} for n in range(2500)}, page=1000)
    assert len(r2.list_keys(bucket, "loremfile-public")) == 2500
    assert bucket.lists == 3


def test_only_keys_the_bucket_holds_are_headed() -> None:
    """On a first deploy that is zero requests; thereafter one per published fixture."""
    bucket = FakeBucket({"pdf/a.pdf": {"sha256": "aa"}})
    live = r2.live_hashes(bucket, "loremfile-public", ["pdf/a.pdf", "pdf/absent.pdf"])

    assert live == {"pdf/a.pdf": "aa"}
    assert bucket.heads == ["pdf/a.pdf"], "an absent key must not be HEADed"


def test_an_object_without_sha256_metadata_reports_unverifiable_not_empty() -> None:
    """`""` would render as a hash mismatch against an empty string; the plan needs to
    be able to say which of the two things went wrong."""
    bucket = FakeBucket({"pdf/a.pdf": {"catalog-version": "1.0.0"}})
    assert r2.live_hashes(bucket, "loremfile-public", ["pdf/a.pdf"]) == {
        "pdf/a.pdf": r2.UNVERIFIABLE
    }


def test_metadata_keys_are_matched_case_insensitively() -> None:
    """S3 lowercases user metadata keys in some paths and not others."""
    bucket = FakeBucket({"pdf/a.pdf": {"SHA256": "bb"}})
    assert r2.live_hashes(bucket, "loremfile-public", ["pdf/a.pdf"]) == {"pdf/a.pdf": "bb"}


def test_missing_credentials_name_where_they_come_from(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "R2_ACCESS_KEY_ID",
        "AWS_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "CLOUDFLARE_ACCOUNT_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(r2.R2Error, match="production"):
        r2.client()


# --- what `build --missing-in-bucket` selects -------------------------------


def test_missing_in_bucket_skips_what_is_published() -> None:
    published = {f.path for f in CATALOG.fixtures() if not f.expected_drift}
    chosen = build_module.select(
        CATALOG, selection=Selection.MISSING_IN_BUCKET, in_bucket=lambda: published
    )
    assert not [f for f in chosen if f.path in published]


def test_missing_in_bucket_never_selects_an_expected_drift_path() -> None:
    """Rebuilding one here would produce bytes the manifest does not describe, and
    `manifest check` would then fail on a fixture the deploy was never going to upload.
    The carry-forward artifact is the only source for these (docs/09 §3.2 gate 2)."""
    chosen = build_module.select(
        CATALOG, selection=Selection.MISSING_IN_BUCKET, in_bucket=nothing_published
    )
    assert not [f for f in chosen if f.expected_drift]


def test_missing_in_bucket_still_selects_everything_else() -> None:
    """Negative control: a selection that returned nothing would pass both tests above."""
    chosen = build_module.select(
        CATALOG, selection=Selection.MISSING_IN_BUCKET, in_bucket=nothing_published
    )
    assert len(chosen) > 100


def test_missing_in_bucket_without_a_listing_refuses_rather_than_building_everything() -> None:
    """Falling back to `--all` would rebuild the whole catalog on a deploy runner —
    including the paths that must never be rebuilt there."""
    with pytest.raises(BuildError, match="bucket listing"):
        build_module.select(CATALOG, selection=Selection.MISSING_IN_BUCKET)


# --- the lock gate reads the committed file, and says so --------------------


def test_the_committed_lock_rules_cover_every_catalogued_prefix() -> None:
    covered = {rule["prefix"] for rule in locks.committed_rules() if rule["enabled"]}
    needed = {f"{fixture.format}/" for fixture in CATALOG.fixtures()}
    assert not needed - covered


def test_the_lock_gate_is_what_stops_a_publish_to_an_uncovered_prefix() -> None:
    """Negative control for the test above: with the rule removed, the gate fires."""
    rules = [rule for rule in locks.committed_rules() if rule["prefix"] != "pdf/"]
    assert _unlocked(["pdf/a4-1page.pdf"], rules) == ["pdf/"]
    assert _unlocked(["pdf/a4-1page.pdf"], locks.committed_rules()) == []


def _unlocked(keys: list[str], rules: list[dict[str, Any]]) -> list[str]:
    from loremfile.infra.upload import unlocked_prefixes  # noqa: PLC0415 - local to the control

    return unlocked_prefixes(keys, rules)


# --- the launch set reconciles ----------------------------------------------

#: `docs/05` §9 and ADR-024. The launch set is an explicit list, not a query.
LAUNCH_SET = 228

#: Rows M3.7 (archives, fonts, mail, calendar, cert, wasm, web) and M3.8 (edge) still
#: have to add. Maintained by hand **on purpose**: it is the one number that cannot be
#: derived from the repository, so the test turns "someone added fixtures without
#: thinking about the launch scope" into a failing build rather than a slow drift.
#:
#: Today it is `228 - 166`, not an independent count of what `05` §9 still lists — that
#: list contains wildcards ("all seven `zero-byte.*`", "all 23 P1 rows of §3.10") which
#: cannot be counted mechanically. M3.7 and M3.8 confirm it by decrementing it to zero;
#: if they cannot, the discrepancy is a `05` §9 finding rather than a test to adjust.
REMAINING_M37_M38 = 62


def test_the_launch_set_still_adds_up() -> None:
    catalogued = len(list(CATALOG.fixtures()))
    assert catalogued + REMAINING_M37_M38 == LAUNCH_SET, (
        f"{catalogued} catalogued + {REMAINING_M37_M38} remaining != {LAUNCH_SET}. "
        "Adding fixtures means decrementing REMAINING_M37_M38 by the same number; if "
        "the launch set itself is meant to change, that is a docs/05 §9 and ADR-024 "
        "decision, not a test edit."
    )


def test_the_five_withheld_fixtures_are_the_gap_between_catalog_and_manifest() -> None:
    """161 published + 5 withheld + 62 to come = 228.

    The five carry `awaiting_publication`: their bytes were never published, so their
    manifest entries were withdrawn outright rather than tombstoned (docs/03 §7.1). They
    return through the carry-forward path, which is why they are counted here rather
    than written off.
    """
    manifest = json.loads((Path(__file__).resolve().parents[2] / "manifest.json").read_text())
    published = [e for e in manifest["fixtures"] if e.get("status", "active") == "active"]
    withheld = [f for f in CATALOG.fixtures() if f.awaiting_publication]

    assert len(published) + len(withheld) == len(list(CATALOG.fixtures()))
    assert len(published) + len(withheld) + REMAINING_M37_M38 == LAUNCH_SET
    assert {f.path for f in withheld} == {f.path for f in CATALOG.fixtures() if f.expected_drift}
