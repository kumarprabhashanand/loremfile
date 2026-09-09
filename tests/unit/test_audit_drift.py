"""`build --audit` must separate expected drift from real drift (docs/06 §8).

Four media fixtures do not reproduce off the CI reference fleet: libx264, libvpx and
libopus each choose SIMD kernels from the CPU features they find, and no ffmpeg flag
reaches that choice (`-cpuflags 0` is byte-identical, on both the Opus and the VP9
paths). They are marked `expected_drift` in the catalog.

The split exists so the monthly audit stays worth reading. An issue that reports the
same four paths every month alongside genuine regressions is one that gets closed
unread — which is how a real regression gets missed. The test that matters most here is
`test_the_marker_cannot_hide_real_drift`: the marker must narrow the report, never the
check that catches a generator changing its output.
"""

from __future__ import annotations

import json
from unittest import mock

from click.testing import CliRunner

from loremfile import cli
from loremfile.build import Built
from loremfile.catalog import Catalog
from loremfile.cli import _names_a_path, _report_audit
from loremfile.manifest import Manifest

#: The paths M3.6 found; docs/06 §4 records why.
KNOWN_SENSITIVE = {
    "mp4/1080p-10s.mp4",
    "mp4/10mb.mp4",
    "mp4/50mb.mp4",
    "opus/30s.opus",
    "webm/720p-5s-vp9.webm",
}


def rebuilt(path: str, sha256: str) -> Built:
    """A Built standing for a regeneration that produced `sha256`."""
    return Built(Catalog.load().by_path[path], b"", sha256)


def audit(builts: list[Built], *, manifest: Manifest | None = None) -> tuple[int, dict]:
    runner = CliRunner()
    loaded = manifest if manifest is not None else Manifest.load()
    with (
        mock.patch.object(cli.Manifest, "load", staticmethod(lambda: loaded)),
        runner.isolation() as output,
    ):
        code = _report_audit(Catalog.load(), builts, as_json=True)
    return code, json.loads(output[0].getvalue().decode())


def manifest_including(path: str) -> Manifest:
    """The committed manifest plus an entry for a path currently withheld from it.

    The five `expected_drift` paths are held out of the manifest until a run can publish
    them (docs/03 §7.1), so the classification below has no live example to work from.
    Rather than drop the coverage, the situation is constructed: this is what the audit
    will meet once M4.3 puts those entries back.
    """
    loaded = Manifest.load()
    template = dict(loaded.by_path["pdf/a4-3pages.pdf"])
    loaded.entries = [*loaded.entries, {**template, "path": path, "sha256": "a" * 64}]
    return loaded


def test_the_marked_paths_are_exactly_the_ones_m36_found() -> None:
    """A new marker is a decision, not a detail: it should fail this test first."""
    marked = {f.path for f in Catalog.load().fixtures() if f.expected_drift}
    assert marked == KNOWN_SENSITIVE, (
        "expected_drift changed. Adding one silences a path in every future audit, so it "
        "belongs in a pull request that says why (docs/06 §4)."
    )


def test_every_marker_explains_itself() -> None:
    for fixture in Catalog.load().fixtures():
        if fixture.expected_drift:
            assert "docs/06" in fixture.expected_drift or "RISK-21" in fixture.expected_drift, (
                f"{fixture.path}: expected_drift must point at the reason"
            )


def test_expected_drift_is_reported_but_does_not_fail_the_audit() -> None:
    code, payload = audit(
        [rebuilt("opus/30s.opus", "f" * 64)], manifest=manifest_including("opus/30s.opus")
    )
    assert code == 0, payload
    assert payload["summary"]["expected_drift"] == 1
    assert payload["summary"]["drifted"] == 0
    assert payload["errors"] == []
    assert payload["items"][0]["status"] == "expected"


def test_the_marker_cannot_hide_real_drift() -> None:
    """An unmarked path that regenerates differently must still fail, loudly.

    This is the control for the whole mechanism: if marking a path could suppress
    anything beyond its own line in the report, the audit would be worth less than not
    having one.
    """
    code, payload = audit([rebuilt("pdf/a4-3pages.pdf", "e" * 64)])
    assert code != 0
    assert payload["summary"]["drifted"] == 1
    assert payload["summary"]["expected_drift"] == 0
    assert any("pdf/a4-3pages.pdf" in e for e in payload["errors"])


def test_both_kinds_are_reported_together_and_the_real_one_decides() -> None:
    code, payload = audit(
        [rebuilt("opus/30s.opus", "f" * 64), rebuilt("pdf/a4-3pages.pdf", "e" * 64)],
        manifest=manifest_including("opus/30s.opus"),
    )
    assert code != 0, "one real drift must fail the run even beside expected drift"
    assert payload["summary"] == {"regenerated": 2, "drifted": 1, "expected_drift": 1}


def test_a_fixture_that_reproduces_is_not_reported_at_all() -> None:
    entry = Manifest.load().by_path["pdf/a4-3pages.pdf"]
    code, payload = audit([rebuilt("pdf/a4-3pages.pdf", entry["sha256"])])
    assert code == 0
    assert payload["items"] == []
    assert payload["summary"]["regenerated"] == 1


def test_audit_is_reachable_from_the_command_line() -> None:
    """The flag has to exist on `build`, or none of the above is ever run."""
    result = CliRunner().invoke(cli.main, ["build", "--help"])
    assert "--audit" in result.output


def test_manifest_check_downgrades_a_marked_path_but_not_its_neighbours() -> None:
    """`manifest check` reports expected drift and keeps failing on everything else.

    Measured in M3.6: two attempts of the same commit on the same runner label produced
    different bytes for `opus/30s.opus` and `webm/720p-5s-vp9.webm`. A check that cannot
    pass twice in a row is a check that someone eventually deletes — but downgrading it
    must not reach any other path, which is what the second half asserts.
    """
    marked = {f.path for f in Catalog.load().fixtures() if f.expected_drift}
    assert _names_a_path("opus/30s.opus: sha256 would change from 'a' to 'b'", marked)
    assert not _names_a_path("pdf/a4-3pages.pdf: sha256 would change from 'a' to 'b'", marked)
    # Exact paths, never prefixes: neither a path that contains a marked one nor a
    # marked one that is a prefix of something else may be swallowed.
    assert not _names_a_path("edge/opus/30s.opus: sha256 would change", marked)
    assert not _names_a_path("opus/30s.opus.bak: sha256 would change", marked)
    assert not _names_a_path("opus/30s.opus", marked), "a message with no diagnostic"


def test_the_withheld_paths_are_absent_from_the_manifest() -> None:
    """M3.6's remedy, asserted: five entries described bytes that existed nowhere.

    They are withheld rather than tombstoned, because a tombstone asserts a publication
    that never happened (docs/03 §7.1, amended in the same milestone).
    """
    committed = set(Manifest.load().by_path)
    catalog = Catalog.load()
    withheld = {f.path for f in catalog.fixtures() if f.awaiting_publication}
    assert withheld == KNOWN_SENSITIVE
    assert not (withheld & committed), "a withheld path is in the manifest"
    assert not any(e.get("status") == "removed" for e in Manifest.load().entries), (
        "withdrawn entries must be removals, not tombstones"
    )
