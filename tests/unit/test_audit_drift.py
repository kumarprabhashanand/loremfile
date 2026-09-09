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

from click.testing import CliRunner

from loremfile import cli
from loremfile.build import Built
from loremfile.catalog import Catalog
from loremfile.cli import _report_audit
from loremfile.manifest import Manifest

#: The paths M3.6 found; docs/06 §4 records why.
KNOWN_SENSITIVE = {
    "mp4/1080p-10s.mp4",
    "mp4/50mb.mp4",
    "opus/30s.opus",
    "webm/720p-5s-vp9.webm",
}


def rebuilt(path: str, sha256: str) -> Built:
    """A Built standing for a regeneration that produced `sha256`."""
    return Built(Catalog.load().by_path[path], b"", sha256)


def audit(builts: list[Built]) -> tuple[int, dict]:
    runner = CliRunner()
    with runner.isolation() as output:
        code = _report_audit(Catalog.load(), builts, as_json=True)
    return code, json.loads(output[0].getvalue().decode())


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
    code, payload = audit([rebuilt("opus/30s.opus", "f" * 64)])
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
        [rebuilt("opus/30s.opus", "f" * 64), rebuilt("pdf/a4-3pages.pdf", "e" * 64)]
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
