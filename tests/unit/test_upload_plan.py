"""M4.3: the upload plan, and the two gates that stop a deploy rather than shape it.

The plan is a pure function so these run without a bucket. What they are really testing
is refusal: an uploader that is merely *usually* right about immutability is an uploader
that eventually overwrites a published byte.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from loremfile.catalog import Catalog
from loremfile.infra import upload
from loremfile.infra.upload import Action

CATALOG = Catalog.load()
LOCKS = json.loads(
    (upload.Path(__file__).resolve().parents[2] / "infra" / "r2-locks.json").read_text()
)["rules"]


def entry(path: str, sha: str = "a" * 64, size: int = 10, status: str = "active") -> dict[str, Any]:
    return {"path": path, "sha256": sha, "bytes": size, "status": status}


def sources(tmp_path: Path, *keys: str) -> dict[str, Path]:
    out = {}
    for key in keys:
        target = tmp_path / key.replace("/", "_")
        target.write_bytes(b"x" * 10)
        out[key] = target
    return out


# --- immutability -----------------------------------------------------------


def test_a_live_object_with_a_different_hash_fails_rather_than_overwrites(
    tmp_path: Path,
) -> None:
    """The single most important line in the module.

    At this point either the manifest or the bucket is wrong, and guessing which is
    exactly how a published byte changes. Note the plan does not offer an `overwrite`
    action at all — there is no value of any flag that produces one.
    """
    plan = upload.plan_fixtures(
        [entry("pdf/a4-3pages.pdf", sha="a" * 64)],
        live={"pdf/a4-3pages.pdf": "b" * 64},
        available=sources(tmp_path, "pdf/a4-3pages.pdf"),
        catalog=CATALOG,
        lock_rules=LOCKS,
    )
    assert not plan.ok
    step = plan.steps[0]
    assert step.action is Action.FAIL
    assert "never change" in step.reason
    assert Action.UPLOAD not in {s.action for s in plan.steps}


def test_there_is_no_overwrite_action() -> None:
    """Asserted on the enum: a flag that could produce one must not be addable by accident."""
    assert {a.value for a in Action} == {"upload", "skip", "remove", "fail"}


def test_a_matching_live_object_is_skipped(tmp_path: Path) -> None:
    plan = upload.plan_fixtures(
        [entry("pdf/a4-3pages.pdf", sha="a" * 64)],
        live={"pdf/a4-3pages.pdf": "a" * 64},
        available=sources(tmp_path, "pdf/a4-3pages.pdf"),
        catalog=CATALOG,
        lock_rules=LOCKS,
    )
    assert plan.ok
    assert plan.steps[0].action is Action.SKIP


def test_a_missing_object_with_no_bytes_fails() -> None:
    plan = upload.plan_fixtures(
        [entry("pdf/a4-3pages.pdf")],
        live={},
        available={},
        catalog=CATALOG,
        lock_rules=LOCKS,
    )
    assert not plan.ok
    assert "no bytes available" in plan.steps[0].reason


# --- gate: no upload to an unlocked prefix ----------------------------------


def test_uploading_to_a_prefix_with_no_lock_rule_is_blocked(tmp_path: Path) -> None:
    """The gate that stops M3's deferral outliving its reason (docs/08 §2)."""
    plan = upload.plan_fixtures(
        [entry("brandnew/thing.bin")],
        live={},
        available=sources(tmp_path, "brandnew/thing.bin"),
        catalog=CATALOG,
        lock_rules=LOCKS,
    )
    assert not plan.ok
    assert any("no bucket lock rule covers" in b for b in plan.blockers)


def test_a_disabled_lock_rule_does_not_count_as_coverage() -> None:
    """A rule that exists and is off protects nothing, and must not read as protection."""
    rules = [{"prefix": "pdf/", "enabled": False}]
    assert upload.unlocked_prefixes(["pdf/x.pdf"], rules) == ["pdf/"]
    assert upload.unlocked_prefixes(["pdf/x.pdf"], [{"prefix": "pdf/", "enabled": True}]) == []


def test_every_catalog_format_is_covered_by_the_committed_rules() -> None:
    """The gate must pass for the real catalog, or no deploy is possible at all."""
    keys = [f"{fmt}/whatever" for fmt in {f.format for f in CATALOG.fixtures()}]
    assert upload.unlocked_prefixes(keys, LOCKS) == []


def test_site_keys_are_not_treated_as_locked_prefixes() -> None:
    """Site keys are mutable by design; the gate must not demand a lock for them."""
    assert upload.prefix_of("index.html") == ""
    assert upload.unlocked_prefixes(["index.html", "sitemap.xml"], []) == []


# --- gate: never rebuild an expected_drift path -----------------------------


def drift_path() -> str:
    return next(f.path for f in CATALOG.fixtures() if f.expected_drift)


def test_an_expected_drift_path_without_carried_bytes_is_blocked(tmp_path: Path) -> None:
    """The deploy must fail, not regenerate. A rebuild produces different bytes."""
    key = drift_path()
    plan = upload.plan_fixtures(
        [entry(key)],
        live={},
        available=sources(tmp_path, key),
        catalog=CATALOG,
        lock_rules=LOCKS,
    )
    assert plan.ok, "with the bytes present it should proceed"

    # The same key, with the carry-forward artifact missing: the bytes present here
    # would be a rebuild, and a rebuild is exactly what must not be published.
    plan = upload.plan_fixtures(
        [entry(key)], live={}, available={}, catalog=CATALOG, lock_rules=LOCKS
    )
    assert not plan.ok
    assert any("carry-forward" in b for b in plan.blockers) or any(
        s.action is Action.FAIL for s in plan.steps
    )


def test_the_gate_names_every_missing_drift_path_not_just_the_first() -> None:
    """Five paths are marked; a deploy should learn about all of them in one run."""
    marked = [f.path for f in CATALOG.fixtures() if f.expected_drift]
    blockers = upload.carry_forward_gate(marked, CATALOG, available={})
    assert len(blockers) == len(marked)


def test_an_ordinary_fixture_needs_no_carry_forward() -> None:
    assert upload.carry_forward_gate(["pdf/a4-3pages.pdf"], CATALOG, available={}) == []


# --- removals ---------------------------------------------------------------


def test_only_tombstoned_entries_are_removed() -> None:
    plan = upload.plan_removals(
        [entry("pdf/a4-3pages.pdf"), entry("pdf/gone.pdf", status="removed")],
        live={"pdf/a4-3pages.pdf": "a" * 64, "pdf/gone.pdf": "c" * 64},
    )
    assert [s.key for s in plan.by_action(Action.REMOVE)] == ["pdf/gone.pdf"]


def test_a_tombstone_that_is_already_gone_is_not_re_deleted() -> None:
    plan = upload.plan_removals([entry("pdf/gone.pdf", status="removed")], live={})
    assert plan.steps == []


def test_removals_never_touch_an_active_entry() -> None:
    """The only delete path besides `probe --down`, and it cannot see anything else."""
    manifest = [entry(f.path) for f in list(CATALOG.fixtures())[:20]]
    live = {e["path"]: e["sha256"] for e in manifest}
    assert upload.plan_removals(manifest, live).steps == []


# --- site -------------------------------------------------------------------


def test_unchanged_site_files_are_skipped_and_force_overrides(tmp_path: Path) -> None:
    page = tmp_path / "index.html"
    page.write_bytes(b"<!doctype html>")
    files = {"index.html": (page, "d" * 64)}

    assert upload.plan_site(files, live={"index.html": "d" * 64}).steps[0].action is Action.SKIP
    forced = upload.plan_site(files, live={"index.html": "d" * 64}, force=True)
    assert forced.steps[0].action is Action.UPLOAD


def test_a_changed_site_file_is_uploaded(tmp_path: Path) -> None:
    page = tmp_path / "index.html"
    page.write_bytes(b"<!doctype html>")
    plan = upload.plan_site({"index.html": (page, "new")}, live={"index.html": "old"})
    assert plan.steps[0].action is Action.UPLOAD


def test_the_plan_reports_what_it_would_do(tmp_path: Path) -> None:
    plan = upload.plan_fixtures(
        [entry("pdf/a4-3pages.pdf", sha="a" * 64), entry("png/1x1.png", sha="b" * 64)],
        live={"png/1x1.png": "z" * 64},
        available=sources(tmp_path, "pdf/a4-3pages.pdf"),
        catalog=CATALOG,
        lock_rules=LOCKS,
    )
    rendered = plan.render()
    assert "upload=1" in rendered
    assert "fail=1" in rendered
    assert "png/1x1.png" in rendered


# --- M4.4: where the bytes come from, and whether they are the right ones ----


def plain_path() -> str:
    return next(f.path for f in CATALOG.fixtures() if not f.expected_drift)


def write(root: Path, key: str, data: bytes) -> Path:
    target = root / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def test_an_expected_drift_path_is_never_read_from_the_build_directory(tmp_path: Path) -> None:
    """The rebuild sitting in build/fixtures/ is the wrong bytes, not a fallback.

    On the deploy runner that file was produced by whichever CPU drew the job, while the
    manifest describes what a different runner produced (docs/06 §4). Offering it would
    make `carry_forward_gate` unreachable: the gate only fires on a *missing* key.
    """
    build_dir = tmp_path / "build"
    write(build_dir, drift_path(), b"a rebuild on this runner")

    found = upload.sources([drift_path()], catalog=CATALOG, build_dir=build_dir)
    assert found == {}, "the rebuild must not be offered as a source"


def test_an_ordinary_path_is_read_from_the_build_directory(tmp_path: Path) -> None:
    """Negative control for the test above: a resolver that found nothing would pass it."""
    build_dir = tmp_path / "build"
    target = write(build_dir, plain_path(), b"freshly built")

    found = upload.sources([plain_path()], catalog=CATALOG, build_dir=build_dir)
    assert found == {plain_path(): target}


def test_an_expected_drift_path_comes_from_the_carry_forward_directory(tmp_path: Path) -> None:
    build_dir = tmp_path / "build"
    carry = tmp_path / "carry-forward"
    write(build_dir, drift_path(), b"a rebuild on this runner")
    carried = write(carry, drift_path(), b"the bytes the manifest describes")

    found = upload.sources(
        [drift_path()], catalog=CATALOG, build_dir=build_dir, carry_forward=carry
    )
    assert found == {drift_path(): carried}


def test_bytes_that_do_not_hash_to_the_manifest_are_refused(tmp_path: Path) -> None:
    """The carry-forward artifact is downloaded from another workflow run.

    That makes it untrusted input, and this is what makes downloading it loosely safe:
    an artifact from the wrong run cannot pass, so provenance is established by content.
    """
    body = b"the right bytes"
    digest = hashlib.sha256(body).hexdigest()
    wrong = write(tmp_path, "wrong.bin", b"not those bytes")
    plan = upload.Plan(steps=[upload.Step("mp4/x.mp4", Action.UPLOAD, source=str(wrong))])

    blockers = upload.verify_sources(plan, [entry("mp4/x.mp4", sha=digest, size=len(body))])
    assert len(blockers) == 1
    assert "Refusing to publish bytes the manifest does not describe" in blockers[0]


def test_bytes_that_do_hash_to_the_manifest_pass(tmp_path: Path) -> None:
    """Negative control: a verifier that refused everything would pass the test above."""
    body = b"the right bytes"
    right = write(tmp_path, "right.bin", body)
    plan = upload.Plan(steps=[upload.Step("mp4/x.mp4", Action.UPLOAD, source=str(right))])

    assert (
        upload.verify_sources(
            plan, [entry("mp4/x.mp4", sha=hashlib.sha256(body).hexdigest(), size=len(body))]
        )
        == []
    )


def test_a_right_hash_with_a_wrong_length_is_still_refused(tmp_path: Path) -> None:
    body = b"the right bytes"
    right = write(tmp_path, "right.bin", body)
    plan = upload.Plan(steps=[upload.Step("mp4/x.mp4", Action.UPLOAD, source=str(right))])

    blockers = upload.verify_sources(
        plan, [entry("mp4/x.mp4", sha=hashlib.sha256(body).hexdigest(), size=len(body) + 1)]
    )
    assert len(blockers) == 1
    assert "bytes, manifest says" in blockers[0]


def test_a_published_object_with_no_sha256_metadata_fails_rather_than_skipping(
    tmp_path: Path,
) -> None:
    """ "Present" is not "correct". Without the metadata there is nothing to compare."""
    key = plain_path()
    plan = upload.plan_fixtures(
        [entry(key)],
        {key: upload.UNVERIFIABLE},
        sources(tmp_path, key),
        catalog=CATALOG,
        lock_rules=LOCKS,
    )
    assert [s.action for s in plan.steps] == [Action.FAIL]
    assert "no sha256 metadata" in plan.steps[0].reason
    assert not plan.ok
