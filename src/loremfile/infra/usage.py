"""R2 operations and zone traffic from the GraphQL Analytics API (docs/06 §10, docs/19).

Read with T4, the read-only analytics token. `health.yml` uses this daily to open a
`cost` issue above the threshold in docs/19 §3.

The dimension that matters for the cost model is **`GetObject` with
`actionStatus: userError`** — a GET for a key that does not exist. docs/19 §3 assumes
those are billed as Class B reads, because R2's pricing FAQ exempts only unauthorized
(401) requests and says nothing about 404s. Reading that dimension directly gives exact
attribution: a delta in *this* counter after firing N unique missing paths is those N
requests and nothing else, rather than a noisy total that other traffic also moves.

The same dimension is also read **by day**, not only month-to-date. A month-to-date counter
cannot express a rate — it is cumulative and resets at the month boundary — and the number
worth keeping is the daily missing-key rate before the site has an audience. That series is
only obtainable while it is inside the API's 90-day retention, so `ops_log` commits it to
the repository rather than leaving it to be re-queried (`docs/19` §3.2).

One distinction the model has to keep. This measures what R2 **records as an operation**.
Whether Cloudflare **bills** a recorded `userError` GetObject is its pricing policy
applied to that record, and no API reports it. The recorded operation is the best
available proxy and docs/19 §3 says so rather than eliding it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from loremfile.infra import scanners

GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"

#: Class B in R2's pricing: reads and metadata operations.
CLASS_B_ACTIONS = frozenset({"GetObject", "HeadObject", "ListObjects", "ListBuckets"})
#: Class A: writes and mutations.
CLASS_A_ACTIONS = frozenset(
    {"PutObject", "DeleteObject", "CopyObject", "CreateBucket", "DeleteBucket"}
)

#: A GET for a key that does not exist — the 404 path docs/19 §3 depends on.
MISSING_KEY_ACTION = "GetObject"
MISSING_KEY_STATUS = "userError"

OPERATIONS_QUERY = """
query Operations($accountTag: string!, $start: Time!, $end: Time!) {
  viewer {
    accounts(filter: {accountTag: $accountTag}) {
      r2OperationsAdaptiveGroups(
        limit: 200,
        filter: {datetime_geq: $start, datetime_leq: $end}
      ) {
        sum { requests }
        dimensions { actionType actionStatus bucketName }
      }
    }
  }
}
"""


#: Both limits are the API's own, read off its refusals on 2026-09-10 rather than off the
#: documentation (`docs/19` §3.2). They bound how much history the daily series can hold:
#: past `RETENTION_DAYS` the pre-launch baseline is not reconstructible at all, which is
#: why the series is committed to the `ops-log` branch instead of re-queried on demand.
#:   "cannot request data older than 12w6d"          -> 90 days
#:   "cannot request a time range wider than 4w4d"   -> 32 days
RETENTION_DAYS = 90
MAX_WINDOW_DAYS = 32

DAILY_QUERY = """
query Daily($accountTag: string!, $start: Time!, $end: Time!) {
  viewer {
    accounts(filter: {accountTag: $accountTag}) {
      r2OperationsAdaptiveGroups(
        limit: 5000,
        orderBy: [date_ASC],
        filter: {datetime_geq: $start, datetime_leq: $end}
      ) {
        sum { requests }
        dimensions { date actionType actionStatus }
      }
    }
  }
}
"""


class UsageError(RuntimeError):
    """The analytics API could not be read, or answered with errors."""


@dataclass
class Operations:
    """Counts for one window, by action and status."""

    rows: list[dict[str, Any]] = field(default_factory=list)

    def total(self, *, actions: frozenset[str] | None = None, status: str | None = None) -> int:
        return sum(
            int(row["sum"]["requests"])
            for row in self.rows
            if (actions is None or row["dimensions"]["actionType"] in actions)
            and (status is None or row["dimensions"]["actionStatus"] == status)
        )

    @property
    def class_a(self) -> int:
        return self.total(actions=CLASS_A_ACTIONS)

    @property
    def class_b(self) -> int:
        return self.total(actions=CLASS_B_ACTIONS)

    @property
    def missing_key_reads(self) -> int:
        """GETs for keys that do not exist — 404s, the vector docs/19 §3 models."""
        return self.total(actions=frozenset({MISSING_KEY_ACTION}), status=MISSING_KEY_STATUS)

    def render(self) -> str:
        lines = [f"  class A {self.class_a:>10,}", f"  class B {self.class_b:>10,}"]
        lines.append(f"    of which missing-key GETs {self.missing_key_reads:>10,}")
        for row in sorted(self.rows, key=lambda r: -int(r["sum"]["requests"])):
            dims = row["dimensions"]
            lines.append(
                f"    {dims['actionType']:<14} {dims['actionStatus']:<10} "
                f"{int(row['sum']['requests']):>10,}"
            )
        return "\n".join(lines)


def _post(token: str, payload: dict[str, Any], *, timeout: int = 60) -> dict[str, Any]:
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body: dict[str, Any] = json.loads(response.read())
    if body.get("errors"):
        messages = "; ".join(e.get("message", "?") for e in body["errors"])
        raise UsageError(f"GraphQL returned errors: {messages}")
    return body


def _token() -> str:
    token = os.environ.get("CLOUDFLARE_ANALYTICS_TOKEN") or os.environ.get(
        "CLOUDFLARE_API_TOKEN", ""
    )
    if not token:
        raise UsageError(
            "CLOUDFLARE_ANALYTICS_TOKEN (T4) is required; it comes from the GitHub "
            "`production` environment (AGENTS.md rule 4)."
        )
    return token


def _account() -> str:
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not account:
        raise UsageError("CLOUDFLARE_ACCOUNT_ID is required.")
    return account


def _stamp(when: dt.datetime) -> str:
    return when.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _rows(body: dict[str, Any], field_name: str) -> list[dict[str, Any]]:
    try:
        accounts = body["data"]["viewer"]["accounts"]
    except (KeyError, TypeError) as exc:
        raise UsageError(f"unexpected GraphQL shape: {body}") from exc
    if not accounts:
        raise UsageError("the analytics token can see no accounts")
    return list(accounts[0].get(field_name) or [])


def operations(start: dt.datetime, end: dt.datetime) -> Operations:
    """R2 operations in a window, by action and status."""
    check_window(start, end)
    body = _post(
        _token(),
        {
            "query": OPERATIONS_QUERY,
            "variables": {
                "accountTag": _account(),
                "start": _stamp(start),
                "end": _stamp(end),
            },
        },
    )
    return Operations(rows=_rows(body, "r2OperationsAdaptiveGroups"))


def month_to_date() -> Operations:
    now = dt.datetime.now(tz=dt.UTC)
    return operations(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now)


@dataclass(frozen=True)
class Day:
    """One calendar day of operations. A rate, unlike the month-to-date counters."""

    date: str
    class_a: int
    class_b: int
    missing_key_reads: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "r2_class_a": self.class_a,
            "r2_class_b": self.class_b,
            "missing_key_reads": self.missing_key_reads,
        }


def check_window(start: dt.datetime, end: dt.datetime, *, now: dt.datetime | None = None) -> None:
    """Refuse a window the API will refuse, naming which limit and by how much.

    Checked here rather than left to the API so the caller gets the limit that was
    exceeded instead of a 200 with an `errors` array, and so the guard can be exercised
    without a network call.
    """
    now = now or dt.datetime.now(tz=dt.UTC)
    span = (end - start).days
    if span > MAX_WINDOW_DAYS:
        raise UsageError(
            f"window of {span} days exceeds the API's maximum of {MAX_WINDOW_DAYS}; "
            "page it in chunks"
        )
    age = (now - start).days
    if age > RETENTION_DAYS:
        raise UsageError(
            f"{age} days ago is past the {RETENTION_DAYS}-day retention; that history is "
            "gone and cannot be re-queried"
        )


def daily(start: dt.datetime, end: dt.datetime, *, now: dt.datetime | None = None) -> list[Day]:
    """Per-day Class A/B and missing-key counts, oldest first.

    Month-to-date counters cannot give a rate: they are cumulative and reset at the month
    boundary. `docs/19` §3.2's pre-launch baseline is a *series*, so it is queried by day.
    """
    check_window(start, end, now=now)
    body = _post(
        _token(),
        {
            "query": DAILY_QUERY,
            "variables": {
                "accountTag": _account(),
                "start": _stamp(start),
                "end": _stamp(end),
            },
        },
    )
    rows = _rows(body, "r2OperationsAdaptiveGroups")
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        dims = row["dimensions"]
        day = buckets.setdefault(dims["date"], {"a": 0, "b": 0, "missing": 0})
        requests = int(row["sum"]["requests"])
        if dims["actionType"] in CLASS_A_ACTIONS:
            day["a"] += requests
        if dims["actionType"] in CLASS_B_ACTIONS:
            day["b"] += requests
        if dims["actionType"] == MISSING_KEY_ACTION and dims["actionStatus"] == MISSING_KEY_STATUS:
            day["missing"] += requests
    return [
        Day(date=date, class_a=day["a"], class_b=day["b"], missing_key_reads=day["missing"])
        for date, day in sorted(buckets.items())
    ]


def recent_days(days: int, *, now: dt.datetime | None = None) -> list[Day]:
    """The last N calendar days, N bounded by the API's own window limit."""
    now = now or dt.datetime.now(tz=dt.UTC)
    return daily(now - dt.timedelta(days=days), now, now=now)


# --- the scanner paths' share of the zone's requests (docs/08 §5.7) ----------------------

#: The Free plan's zone request analytics: 7 days of history, at most 24 hours per query
#: (Cloudflare's Security Analytics limits table, read 2026-10-02). Complete UTC days only,
#: and only those wholly inside the retention, so no day is a truncated one.
SCANNER_DAYS = 6

SCANNER_QUERY = """
query Scanners($zoneTag: string!, $start: Time!, $end: Time!) {
  viewer {
    zones(filter: {zoneTag: $zoneTag}) {
      everything: httpRequestsAdaptiveGroups(
        limit: 1,
        filter: {datetime_geq: $start, datetime_lt: $end, requestSource: "eyeball"}
      ) { count }
      scanners: httpRequestsAdaptiveGroups(
        limit: 1,
        filter: {datetime_geq: $start, datetime_lt: $end, requestSource: "eyeball", OR: %s}
      ) { count }
    }
  }
}
"""

#: Asked separately, so a field the schema refuses costs only the evidence that the counts
#: were not sampled, never the counts themselves.
SAMPLING_QUERY = """
query Sampling($zoneTag: string!, $start: Time!, $end: Time!) {
  viewer {
    zones(filter: {zoneTag: $zoneTag}) {
      httpRequestsAdaptiveGroups(
        limit: 1,
        filter: {datetime_geq: $start, datetime_lt: $end, requestSource: "eyeball"}
      ) { avg { sampleInterval } }
    }
  }
}
"""


def _zone() -> str:
    zone = os.environ.get("CLOUDFLARE_ZONE_ID", "")
    if not zone:
        raise UsageError("CLOUDFLARE_ZONE_ID is required.")
    return zone


def _graphql_or(terms: list[dict[str, Any]]) -> str:
    """A list of `{field: "value"}` filters as a GraphQL literal: keys bare, values quoted."""
    return (
        "["
        + ", ".join(
            "{" + ", ".join(f"{key}: {json.dumps(value)}" for key, value in term.items()) + "}"
            for term in terms
        )
        + "]"
    )


def _zone_groups(body: dict[str, Any], alias: str) -> list[dict[str, Any]]:
    try:
        zones = body["data"]["viewer"]["zones"]
    except (KeyError, TypeError) as exc:
        raise UsageError(f"unexpected GraphQL shape: {body}") from exc
    if not zones:
        raise UsageError("the analytics token can see no zone")
    return list(zones[0].get(alias) or [])


def _count(groups: list[dict[str, Any]]) -> int:
    return sum(int(group.get("count") or 0) for group in groups)


@dataclass(frozen=True)
class ScannerDay:
    """One UTC day: every request, and those for a path the scanner rule names."""

    date: str
    requests: int
    scanner_requests: int
    sample_interval: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "requests": self.requests,
            "scanner_requests": self.scanner_requests,
            "sample_interval": self.sample_interval,
        }


def scanner_days(days: int = SCANNER_DAYS, *, now: dt.datetime | None = None) -> list[ScannerDay]:
    """Requests for the scanner paths against all requests, one complete UTC day at a time.

    The paths are `scanners.analytics_filter()`, the list the rule's expression is generated
    from, so this counts exactly what the rule blocks — before it existed and after, since a
    blocked request is still a request in these analytics.
    """
    now = now or dt.datetime.now(tz=dt.UTC)
    today = now.astimezone(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    query = SCANNER_QUERY % _graphql_or(scanners.analytics_filter())
    found: list[ScannerDay] = []
    for back in range(days, 0, -1):
        start = today - dt.timedelta(days=back)
        variables = {
            "zoneTag": _zone(),
            "start": _stamp(start),
            "end": _stamp(start + dt.timedelta(days=1)),
        }
        body = _post(_token(), {"query": query, "variables": variables})
        try:
            sampled = _post(_token(), {"query": SAMPLING_QUERY, "variables": variables})
            groups = _zone_groups(sampled, "httpRequestsAdaptiveGroups")
            interval = max(
                (float(group["avg"]["sampleInterval"]) for group in groups), default=None
            )
        except (UsageError, KeyError, TypeError, ValueError):
            interval = None
        found.append(
            ScannerDay(
                date=start.date().isoformat(),
                requests=_count(_zone_groups(body, "everything")),
                scanner_requests=_count(_zone_groups(body, "scanners")),
                sample_interval=interval,
            )
        )
    return found


def scanner_summary(found: list[ScannerDay]) -> dict[str, Any]:
    """The share over exactly the days counted, from one dataset: no extrapolation.

    A sample interval above 1 on any day means Cloudflare estimated that day, so `unsampled`
    is false; an interval that could not be read makes it None, because unknown is not yes.
    """
    requests = sum(day.requests for day in found)
    scanner = sum(day.scanner_requests for day in found)
    intervals = [day.sample_interval for day in found]
    unsampled: bool | None = None
    if found and all(interval is not None for interval in intervals):
        unsampled = all(interval == 1 for interval in intervals)
    return {
        "days": [day.as_dict() for day in found],
        "from": found[0].date if found else None,
        "to": found[-1].date if found else None,
        "requests": requests,
        "scanner_requests": scanner,
        "share": scanner / requests if requests else None,
        "unsampled": unsampled,
    }


def render_scanners(summary: dict[str, Any]) -> str:
    share = summary["share"]
    sampling = {True: "unsampled", False: "SAMPLED, so estimated", None: "sampling unknown"}
    lines = [
        f"  scanner paths, {summary['from']} to {summary['to']} "
        f"({len(summary['days'])} complete UTC days): {summary['scanner_requests']:,} of "
        f"{summary['requests']:,} requests"
        + (f" ({share:.3%})" if share is not None else "")
        + f", {sampling[summary['unsampled']]}"
    ]
    lines += [
        f"    {day['date']}  {day['scanner_requests']:>6,} of {day['requests']:>8,}"
        for day in summary["days"]
    ]
    return "\n".join(lines)
