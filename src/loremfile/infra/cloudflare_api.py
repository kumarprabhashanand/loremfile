"""Cloudflare API client: auth, retry, pagination — and zone scoping (docs/08 §6).

The scoping guard is the reason this module exists as a class rather than a handful of
functions. This account holds two unrelated production zones, and `apply.py` writes
ruleset entry points with a **full PUT**: a request aimed at the wrong zone id does not
drift someone else's rules, it replaces them. That is the one place in this project
where a mistake reaches something that is not ours.

So the zone id is verified against the hostname before any write is permitted, once per
client, and every write additionally asserts that the path it is about to send addresses
that verified zone. `docs/10` §3 states the intent; :meth:`Client.verify_zone` is the
part that cannot be forgotten under time pressure.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from loremfile.config import SITE_HOST

API_ROOT = "https://api.cloudflare.com/client/v4"

#: HTTP status at or above which a response is an error.
HTTP_ERROR = 400

#: `/zones/{id}/...` — the zone id is the third path segment once split on "/".
ZONE_ID_SEGMENT = 2

#: Retry on these; anything else is a real answer and is returned to the caller.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = 2.0

#: Methods that change state. Every one of them goes through the scoping assertion.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CloudflareError(RuntimeError):
    """An API call failed, or a safety precondition was not met."""


class ReadOnlyError(CloudflareError):
    """A write was attempted through a client that promised not to make any.

    `audit.yml` runs with T1 because Cloudflare tokens cannot be split read/write per
    call (`docs/09` §3.4), so "the audit never writes" was a property of the code being
    read correctly. This makes it a property of the client instead: an audit that grew a
    write would raise here rather than quietly converge the drift it was sent to report.
    """


class ZoneScopeError(CloudflareError):
    """A write was aimed somewhere other than the verified zone. Always fatal.

    Separate from CloudflareError so that no `except CloudflareError` anywhere can
    accidentally swallow it: this is the guard that protects the other zones on the
    account, and it must never degrade into a warning.
    """


@dataclass
class Response:
    status: int
    body: dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.status < HTTP_ERROR and bool(self.body.get("success", True))

    @property
    def result(self) -> Any:  # noqa: ANN401 - the API returns dicts, lists and nulls
        return self.body.get("result")

    @property
    def errors(self) -> str:
        return (
            "; ".join(
                f"{e.get('code', '?')}: {e.get('message', '')}" for e in self.body.get("errors", [])
            )
            or f"HTTP {self.status}"
        )


@dataclass
class Client:
    """Talks to Cloudflare for exactly one zone and one account."""

    token: str
    zone_id: str
    account_id: str
    dry_run: bool = False
    #: Refuse every write outright, rather than no-opping it as `dry_run` does. The two
    #: are different promises: a dry run is a *rehearsal* of writing and reports what it
    #: would have done; a read-only client asserts that writing is not part of the job.
    read_only: bool = False
    #: Set by :meth:`verify_zone`. Until then no write is allowed to leave the process.
    verified_hostname: str | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def from_env(cls, *, dry_run: bool = False, read_only: bool = False) -> Client:
        missing = [
            name
            for name in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ZONE_ID", "CLOUDFLARE_ACCOUNT_ID")
            if not os.environ.get(name)
        ]
        if missing:
            raise CloudflareError(
                f"missing environment: {', '.join(missing)}. These come from the GitHub "
                "`production` environment; nothing runs with local credentials "
                "(AGENTS.md rule 4)."
            )
        return cls(
            token=os.environ["CLOUDFLARE_API_TOKEN"],
            zone_id=os.environ["CLOUDFLARE_ZONE_ID"],
            account_id=os.environ["CLOUDFLARE_ACCOUNT_ID"],
            dry_run=dry_run,
            read_only=read_only,
        )

    # --- the guard ---------------------------------------------------------

    def verify_zone(self, expected_hostname: str = SITE_HOST) -> str:
        """Read the zone and refuse to continue unless it is the one we mean.

        Called before anything writes. Returns the hostname so the caller can print it:
        a dry run that does not show which zone it is pointed at proves nothing.
        """
        response = self.get(f"/zones/{self.zone_id}")
        if not response.ok:
            raise ZoneScopeError(
                f"cannot read zone {self.zone_id}: {response.errors}. Refusing to write "
                "to a zone whose identity could not be confirmed."
            )
        name = str((response.result or {}).get("name", ""))
        if name != expected_hostname:
            raise ZoneScopeError(
                f"CLOUDFLARE_ZONE_ID {self.zone_id} is zone '{name}', not "
                f"'{expected_hostname}'. This account holds unrelated production zones "
                "and ruleset writes are a full PUT, which would replace their rules. "
                "Nothing has been written."
            )
        self.verified_hostname = name
        return name

    def _assert_scoped(self, method: str, path: str) -> None:
        if method not in WRITE_METHODS:
            return
        if self.verified_hostname is None:
            raise ZoneScopeError(
                f"{method} {path} attempted before verify_zone(). The zone identity must "
                "be confirmed before any write (docs/08 §6, docs/10 §3)."
            )
        if path.startswith("/zones/") and not path.startswith(f"/zones/{self.zone_id}"):
            segments = path.split("/")
            other = segments[ZONE_ID_SEGMENT] if len(segments) > ZONE_ID_SEGMENT else "?"
            raise ZoneScopeError(
                f"{method} {path} targets zone {other}, not the verified zone "
                f"{self.zone_id} ({self.verified_hostname})."
            )
        if path.startswith("/accounts/") and not path.startswith(f"/accounts/{self.account_id}"):
            raise ZoneScopeError(f"{method} {path} targets an account that is not ours.")

    # --- transport ---------------------------------------------------------

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Response:
        if self.read_only and method in WRITE_METHODS:
            raise ReadOnlyError(
                f"{method} {path} attempted through a read-only client. The audit reports "
                "state; it does not converge it (docs/09 §3.4)."
            )
        self._assert_scoped(method, path)
        self.calls.append((method, path))
        if self.dry_run and method in WRITE_METHODS:
            return Response(status=200, body={"success": True, "result": {}, "dry_run": True})
        return self._send(method, path, payload)

    def _send(self, method: str, path: str, payload: dict[str, Any] | None) -> Response:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        last: Response | None = None
        for attempt in range(MAX_ATTEMPTS):
            request = urllib.request.Request(  # noqa: S310 - fixed https API root
                f"{API_ROOT}{path}",
                data=data,
                method=method,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as raw:  # noqa: S310
                    return Response(status=raw.status, body=json.loads(raw.read() or b"{}"))
            except urllib.error.HTTPError as exc:
                body = {}
                try:
                    body = json.loads(exc.read() or b"{}")
                except (ValueError, OSError):
                    body = {"errors": [{"code": exc.code, "message": exc.reason}]}
                last = Response(status=exc.code, body=body)
                if exc.code not in RETRY_STATUS:
                    return last
            except urllib.error.URLError as exc:
                last = Response(
                    status=0, body={"errors": [{"code": 0, "message": str(exc.reason)}]}
                )
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_SECONDS * (2**attempt))
        return last or Response(status=0, body={"errors": [{"message": "no response"}]})

    def get(self, path: str) -> Response:
        return self.request("GET", path)

    def put(self, path: str, payload: dict[str, Any]) -> Response:
        return self.request("PUT", path, payload)

    def patch(self, path: str, payload: dict[str, Any]) -> Response:
        return self.request("PATCH", path, payload)

    def post(self, path: str, payload: dict[str, Any]) -> Response:
        return self.request("POST", path, payload)

    def paginate(self, path: str, *, per_page: int = 100) -> list[dict[str, Any]]:
        """Every page of a list endpoint, or a clear failure."""
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            joiner = "&" if "?" in path else "?"
            response = self.get(f"{path}{joiner}page={page}&per_page={per_page}")
            if not response.ok:
                raise CloudflareError(f"GET {path} page {page}: {response.errors}")
            batch = response.result or []
            items.extend(batch)
            info = response.body.get("result_info") or {}
            if page >= int(info.get("total_pages", 1) or 1) or not batch:
                return items
            page += 1
