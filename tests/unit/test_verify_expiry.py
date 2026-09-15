"""The domain and certificate expiry checks: the only warning before either lapses."""

from __future__ import annotations

import datetime as dt
import io
import json

import pytest
from click.testing import CliRunner

from loremfile import cli
from loremfile.infra import verify_live
from loremfile.infra.verify_live import Status

NOW = dt.datetime(2026, 9, 15, tzinfo=dt.UTC)


def at(days: int) -> dt.datetime:
    return NOW + dt.timedelta(days=days, hours=1)


@pytest.mark.parametrize(
    ("days", "status"),
    [(400, Status.OK), (45, Status.OK), (44, Status.RDAP_EXPIRY), (-3, Status.RDAP_EXPIRY)],
)
def test_the_domain_warns_under_45_days(days: int, status: Status) -> None:
    finding = verify_live.check_expiry(
        "domain:x", Status.RDAP_EXPIRY, lambda: at(days), warn_days=45, now=NOW
    )
    assert finding.status is status


def test_an_expiry_that_cannot_be_read_is_a_finding_not_a_pass() -> None:
    def broken() -> dt.datetime:
        raise OSError("connection reset")

    finding = verify_live.check_expiry("tls:x", Status.TLS_EXPIRY, broken, warn_days=14, now=NOW)
    assert finding.status is Status.TLS_EXPIRY
    assert "could not read" in finding.detail


class Opened(io.BytesIO):
    def __enter__(self) -> Opened:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def rdap(monkeypatch: pytest.MonkeyPatch, events: list[dict[str, str]]) -> None:
    monkeypatch.setattr(
        verify_live.urllib.request,
        "urlopen",
        lambda *_a, **_k: Opened(json.dumps({"events": events}).encode()),
    )


def test_the_rdap_expiration_event_is_the_date(monkeypatch: pytest.MonkeyPatch) -> None:
    rdap(
        monkeypatch,
        [
            {"eventAction": "registration", "eventDate": "2026-09-07T13:12:42.987Z"},
            {"eventAction": "expiration", "eventDate": "2027-09-07T13:12:42.987Z"},
        ],
    )
    assert verify_live.registration_expiry() == dt.datetime(
        2027, 9, 7, 13, 12, 42, 987000, tzinfo=dt.UTC
    )


def test_a_record_without_an_expiration_event_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rdap(monkeypatch, [{"eventAction": "registration", "eventDate": "2026-09-07T13:12:42Z"}])
    finding = verify_live.check_expiry(
        "domain:x", Status.RDAP_EXPIRY, verify_live.registration_expiry, warn_days=45, now=NOW
    )
    assert finding.status is Status.RDAP_EXPIRY


def test_not_after_is_read_as_utc() -> None:
    assert verify_live.parse_not_after("Dec  7 06:23:04 2026 GMT") == dt.datetime(
        2026, 12, 7, 6, 23, 4, tzinfo=dt.UTC
    )


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--mode", "daily"], True),
        (["--mode", "full"], True),
        (["--mode", "smoke"], False),
        (["--mode", "full", "--only", "pdf/minimal.pdf"], False),
    ],
)
def test_daily_and_full_check_expiry_and_smoke_and_only_do_not(
    monkeypatch: pytest.MonkeyPatch, args: list[str], expected: bool
) -> None:
    asked: list[bool] = []
    monkeypatch.setattr(verify_live, "expiry_findings", lambda: asked.append(True) or [])
    monkeypatch.setattr(
        verify_live, "fetch", lambda *_a, **_k: verify_live.Response(status=404, headers={})
    )
    CliRunner().invoke(cli.main, ["verify-live", *args, "--json"])
    assert bool(asked) is expected


def test_the_statuses_are_the_documented_vocabulary() -> None:
    """docs/06 §10 names them; the health issue and runbook §7.1 key off the strings."""
    assert {Status.RDAP_EXPIRY.value, Status.TLS_EXPIRY.value} == {"rdap_expiry", "tls_expiry"}
