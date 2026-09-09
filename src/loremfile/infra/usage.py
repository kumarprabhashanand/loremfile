"""R2 operations and zone traffic from the GraphQL Analytics API (docs/06 §10, docs/19).

Read with T4, the read-only analytics token. `health.yml` uses this daily to open a
`cost` issue above the threshold in docs/19 §3.

The dimension that matters for the cost model is **`GetObject` with
`actionStatus: userError`** — a GET for a key that does not exist. docs/19 §3 assumes
those are billed as Class B reads, because R2's pricing FAQ exempts only unauthorized
(401) requests and says nothing about 404s. Reading that dimension directly gives exact
attribution: a delta in *this* counter after firing N unique missing paths is those N
requests and nothing else, rather than a noisy total that other traffic also moves.

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


def operations(start: dt.datetime, end: dt.datetime) -> Operations:
    """R2 operations in a window, by action and status."""
    token = os.environ.get("CLOUDFLARE_ANALYTICS_TOKEN") or os.environ.get(
        "CLOUDFLARE_API_TOKEN", ""
    )
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not token or not account:
        raise UsageError(
            "CLOUDFLARE_ANALYTICS_TOKEN (T4) and CLOUDFLARE_ACCOUNT_ID are required; "
            "they come from the GitHub `production` environment (AGENTS.md rule 4)."
        )
    body = _post(
        token,
        {
            "query": OPERATIONS_QUERY,
            "variables": {
                "accountTag": account,
                "start": start.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
                "end": end.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
            },
        },
    )
    try:
        accounts = body["data"]["viewer"]["accounts"]
    except (KeyError, TypeError) as exc:
        raise UsageError(f"unexpected GraphQL shape: {body}") from exc
    if not accounts:
        raise UsageError("the analytics token can see no accounts")
    return Operations(rows=list(accounts[0].get("r2OperationsAdaptiveGroups") or []))


def month_to_date() -> Operations:
    now = dt.datetime.now(tz=dt.UTC)
    return operations(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now)
