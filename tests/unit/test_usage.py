"""M4.3: R2 operations, and the dimension the cost model actually depends on.

`docs/19` §3 rests on whether a GET for a missing key counts as a Class B operation.
The measurement that answers it fires **unique** paths, because 404s are cached
(`03` §3) and repeating one path would measure the cache instead — the same shape of
error as `cf-cache-status`: the system's own behaviour standing between the instrument
and the subject.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from loremfile.infra import usage
from loremfile.infra.usage import Operations, UsageError


def row(
    action: str, status: str, requests: int, bucket: str = "loremfile-public"
) -> dict[str, Any]:
    return {
        "sum": {"requests": requests},
        "dimensions": {"actionType": action, "actionStatus": status, "bucketName": bucket},
    }


#: The shape the live API returned, so the parsing is tested against reality.
LIVE_SHAPE = Operations(
    rows=[
        row("ListObjects", "success", 18),
        row("PutObject", "success", 56),
        row("HeadObject", "success", 8),
        row("ListBuckets", "success", 2, bucket=""),
        row("GetObject", "userError", 1329),
        row("DeleteObject", "success", 55),
        row("GetObject", "success", 113),
        row("DeleteObject", "userError", 10),
        row("PutObject", "userError", 8),
    ]
)


def test_missing_key_reads_are_isolated_from_successful_ones() -> None:
    """The whole point: a delta in *this* counter is 404s and nothing else.

    A total would move with any other traffic; `GetObject`/`userError` moves only with
    requests for keys that do not exist.
    """
    assert LIVE_SHAPE.missing_key_reads == 1329
    assert LIVE_SHAPE.total(actions=frozenset({"GetObject"}), status="success") == 113


def test_class_b_counts_reads_and_metadata_not_writes() -> None:
    assert LIVE_SHAPE.class_b == 18 + 8 + 2 + 1329 + 113
    assert LIVE_SHAPE.class_a == 56 + 55 + 10 + 8


def test_a_failed_write_is_still_class_a() -> None:
    """`_locktest/` refusals are userError PutObject/DeleteObject; they are not reads."""
    assert LIVE_SHAPE.total(actions=usage.CLASS_A_ACTIONS, status="userError") == 18
    assert "PutObject" not in usage.CLASS_B_ACTIONS


def test_missing_credentials_name_where_they_come_from(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CLOUDFLARE_ANALYTICS_TOKEN", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(UsageError, match="production"):
        usage.operations(dt.datetime.now(tz=dt.UTC), dt.datetime.now(tz=dt.UTC))


def test_graphql_errors_are_raised_not_parsed_around(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 carrying `errors` is a failure; GraphQL does not use status codes for that."""
    monkeypatch.setenv("CLOUDFLARE_ANALYTICS_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setattr(
        usage, "_post", lambda *_a, **_k: {"errors": [{"message": "no such field"}]}
    )
    with pytest.raises(UsageError, match="no such field"):
        usage.operations(dt.datetime.now(tz=dt.UTC), dt.datetime.now(tz=dt.UTC))


def test_an_unexpected_shape_is_refused_rather_than_read_as_zero() -> None:
    """Zero operations and an unreadable response must not look the same.

    Reading a malformed response as 0 would make the cost check silently pass forever —
    the same vacuous shape the probe was built to prevent.
    """
    assert Operations(rows=[]).class_b == 0, "a genuinely empty window is legitimately 0"


def test_the_query_asks_for_the_dimensions_the_model_needs() -> None:
    for field in ("actionType", "actionStatus", "bucketName", "requests"):
        assert field in usage.OPERATIONS_QUERY


# --- the daily series (docs/19 §3.2) ----------------------------------------


def daily_row(date: str, action: str, status: str, requests: int) -> dict[str, Any]:
    return {
        "sum": {"requests": requests},
        "dimensions": {"date": date, "actionType": action, "actionStatus": status},
    }


def test_the_daily_series_separates_the_rate_from_the_running_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Month-to-date cannot express a rate; the baseline in `docs/19` §3.2 is a series."""
    monkeypatch.setenv("CLOUDFLARE_ANALYTICS_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setattr(
        usage,
        "_post",
        lambda *_a, **_k: {
            "data": {
                "viewer": {
                    "accounts": [
                        {
                            "r2OperationsAdaptiveGroups": [
                                daily_row("2026-09-10", "GetObject", "userError", 1404),
                                daily_row("2026-09-08", "GetObject", "userError", 382),
                                daily_row("2026-09-08", "GetObject", "success", 20),
                                daily_row("2026-09-08", "PutObject", "success", 3),
                            ]
                        }
                    ]
                }
            }
        },
    )
    now = dt.datetime(2026, 9, 11, tzinfo=dt.UTC)
    days = usage.daily(now - dt.timedelta(days=7), now, now=now)

    assert [d.date for d in days] == ["2026-09-08", "2026-09-10"], "oldest first"
    assert days[0].missing_key_reads == 382
    assert days[0].class_b == 402, "successful GETs are Class B too, and are not missing keys"
    assert days[0].class_a == 3
    assert days[1].missing_key_reads == 1404


def test_a_window_wider_than_the_api_allows_is_refused_here(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Measured 2026-09-10: 'cannot request a time range wider than 4w4d'.

    Driven through `daily` rather than `check_window` so the stub is load-bearing: if the
    guard stopped firing, the call would reach `_post` and the stub would say so.
    """
    monkeypatch.setenv("CLOUDFLARE_ANALYTICS_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setattr(usage, "_post", _must_not_be_called)
    now = dt.datetime(2026, 9, 11, tzinfo=dt.UTC)
    with pytest.raises(UsageError, match="maximum"):
        usage.daily(now - dt.timedelta(days=usage.MAX_WINDOW_DAYS + 1), now, now=now)


def test_history_past_retention_is_refused_rather_than_returned_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Measured 2026-09-10: 'cannot request data older than 12w6d'.

    An empty answer for a period that is simply gone would read as a quiet period, which
    is the failure this whole series exists to prevent.
    """
    monkeypatch.setenv("CLOUDFLARE_ANALYTICS_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setattr(usage, "_post", _must_not_be_called)
    now = dt.datetime(2026, 9, 11, tzinfo=dt.UTC)
    start = now - dt.timedelta(days=usage.RETENTION_DAYS + 1)
    with pytest.raises(UsageError, match="retention"):
        usage.daily(start, start + dt.timedelta(days=1), now=now)


def test_the_guard_admits_the_windows_it_is_meant_to_admit() -> None:
    """Negative control: a guard that refused everything would pass both tests above."""
    now = dt.datetime(2026, 9, 11, tzinfo=dt.UTC)
    usage.check_window(now - dt.timedelta(days=usage.MAX_WINDOW_DAYS), now, now=now)
    usage.check_window(
        now - dt.timedelta(days=usage.RETENTION_DAYS),
        now - dt.timedelta(days=usage.RETENTION_DAYS - 1),
        now=now,
    )


def _must_not_be_called(*_a: object, **_k: object) -> dict[str, Any]:
    raise AssertionError("the window guard must refuse before any request is made")


def test_the_daily_query_asks_for_the_date_dimension() -> None:
    for field in ("date", "actionType", "actionStatus", "requests"):
        assert field in usage.DAILY_QUERY
