"""Contract checks against production (docs/12 §4). No credentials, any machine.

This is the counterpart to `probe.py` and the two must not be confused. The probe
*provokes* the rate limit and treats a 429 as the result it is looking for. `verify-live`
is checking whether published bytes and headers match the manifest, and a 429 from our
own rate limit is noise on the way to that answer — so **here a 429 is retried after
10 seconds**, which is exactly the behaviour the probe must never have.

They are separate modules with separate fetchers on purpose. A shared one with a flag
would be one wrong argument away from a probe that cannot observe the thing it exists to
observe.

`--inject-failure` reports a path as failing without it being so (REQ-27): the issue
automation is a control, and a control nobody has seen fire is one nobody can trust.
"""

from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from loremfile.config import FIXTURE_CACHE_CONTROL, SITE_HOST


#: docs/06 §10 fixes this vocabulary; the issue automation keys off it.
class Status(StrEnum):
    OK = "ok"
    MISSING_OBJECT = "missing_object"
    CONTENT_LENGTH_MISMATCH = "content_length_mismatch"
    CONTENT_TYPE_MISMATCH = "content_type_mismatch"
    HASH_MISMATCH = "hash_mismatch"
    HEADER_MISSING = "header_missing"
    HEADER_VALUE = "header_value"
    STATUS = "status"
    TIMEOUT = "timeout"


#: Our own rate limit answering. Retried, unlike in the probe (see the module docstring).
HTTP_TOO_MANY_REQUESTS = 429
RATE_LIMIT_BACKOFF_SECONDS = 10
MAX_RATE_LIMIT_RETRIES = 3

#: Headers REQ-03/04/05 require on every fixture. Presence only; the ones whose value
#: is fixed are in `EXPECTED_FIXTURE_HEADERS` below, and `content-type`/`content-length`
#: are compared against the manifest entry rather than a constant.
REQUIRED_FIXTURE_HEADERS = (
    "content-type",
    "content-length",
    "content-disposition",
)

#: docs/03 §4.1, exactly. **Presence is not the contract**: a header rule that fires with
#: the wrong value passes a presence check and breaks the contract anyway, and the values
#: here are frozen — the first three come from object metadata written at upload, under a
#: bucket lock that makes them unchangeable afterwards. Checking them is the only way to
#: find out before the lock closes.
EXPECTED_FIXTURE_HEADERS: dict[str, str] = {
    "cache-control": FIXTURE_CACHE_CONTROL,
    "accept-ranges": "bytes",
    "x-content-type-options": "nosniff",
    "cross-origin-resource-policy": "cross-origin",
    "timing-allow-origin": "*",
    "x-robots-tag": "noindex",
}


def expected_disposition(path: str) -> str:
    """docs/03 §4.1: `inline; filename="{last path segment}"`."""
    return f'inline; filename="{path.rsplit("/", 1)[-1]}"'


#: docs/12 §4: `daily` hashes everything below this and samples above it; `full` hashes
#: everything. The line exists because hashing 0.6 GB daily is not a daily job.
DAILY_HASH_LIMIT_BYTES = 1_000_000

#: Markup is sandboxed; a PDF or a video must **not** carry a CSP, or viewers break.
MARKUP_SUFFIXES = (".html", ".htm", ".xhtml", ".svg", ".xml")


@dataclass
class Finding:
    path: str
    status: Status
    detail: str = ""


@dataclass
class LiveReport:
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(f.status is Status.OK for f in self.findings)

    def add(self, path: str, status: Status, detail: str = "") -> None:
        self.findings.append(Finding(path, status, detail))

    def failures(self) -> list[Finding]:
        return [f for f in self.findings if f.status is not Status.OK]

    def render(self) -> str:
        bad = self.failures()
        lines = [f"  {len(self.findings)} checked, {len(bad)} failing"]
        lines += [f"    {f.status.value:<24} {f.path}  {f.detail}".rstrip() for f in bad]
        return "\n".join(lines)


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes = b""

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")


def fetch(
    path: str, *, method: str = "HEAD", extra_headers: dict[str, str] | None = None
) -> Response:
    """One request, retrying **only** a 429 from our own rate limit.

    docs/12 §4. The retry is the documented behaviour for this tool and the reason it
    cannot share a fetcher with `probe.py`, where the absence of a 429 is the failure.
    """
    for attempt in range(MAX_RATE_LIMIT_RETRIES):
        response = _once(path, method=method, extra_headers=extra_headers)
        if response.status != HTTP_TOO_MANY_REQUESTS:
            return response
        if attempt < MAX_RATE_LIMIT_RETRIES - 1:
            time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
    return response


def _once(path: str, *, method: str, extra_headers: dict[str, str] | None = None) -> Response:
    request = urllib.request.Request(
        f"https://{SITE_HOST}{path}", method=method, headers=extra_headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as raw:  # noqa: S310
            return Response(
                status=raw.status,
                headers={k.lower(): v for k, v in raw.headers.items()},
                body=raw.read() if method == "GET" else b"",
            )
    except urllib.error.HTTPError as exc:
        return Response(
            status=exc.code, headers={k.lower(): v for k, v in (exc.headers or {}).items()}
        )
    except (urllib.error.URLError, TimeoutError):
        return Response(status=0, headers={})


def check_fixture_headers(entry: dict[str, Any], response: Response) -> list[Finding]:
    """The header and length contract for one published fixture."""
    path = entry["path"]
    findings: list[Finding] = []
    if response.status == 0:
        return [Finding(path, Status.TIMEOUT, "no response")]
    if response.status == 404:  # noqa: PLR2004 - the only status with its own meaning here
        return [Finding(path, Status.MISSING_OBJECT, "404")]
    if response.status != 200:  # noqa: PLR2004
        return [Finding(path, Status.STATUS, str(response.status))]

    wanted = {**EXPECTED_FIXTURE_HEADERS, "content-disposition": expected_disposition(path)}
    missing = [
        h for h in (*REQUIRED_FIXTURE_HEADERS, *EXPECTED_FIXTURE_HEADERS) if not response.header(h)
    ]
    if missing:
        findings.append(Finding(path, Status.HEADER_MISSING, ", ".join(sorted(set(missing)))))
    for name, expected in sorted(wanted.items()):
        served = response.header(name)
        if served and served != expected:
            findings.append(
                Finding(path, Status.HEADER_VALUE, f"{name}: {served!r} != {expected!r}")
            )

    length = response.header("content-length")
    if length and int(length) != int(entry["bytes"]):
        findings.append(
            Finding(path, Status.CONTENT_LENGTH_MISMATCH, f"{length} != {entry['bytes']}")
        )
    served_type = response.header("content-type")
    if served_type and served_type != entry["mime"]:
        findings.append(
            Finding(path, Status.CONTENT_TYPE_MISMATCH, f"{served_type!r} != {entry['mime']!r}")
        )

    csp = response.header("content-security-policy")
    markup = path.endswith(MARKUP_SUFFIXES)
    if markup and "sandbox" not in csp:
        findings.append(Finding(path, Status.HEADER_MISSING, "sandbox CSP on markup"))
    if not markup and csp:
        # A CSP on a PDF or a video is not a missing header — it is an extra one that
        # breaks viewers, and it would otherwise pass every check above.
        findings.append(Finding(path, Status.HEADER_MISSING, f"unexpected CSP: {csp[:40]}"))
    return findings or [Finding(path, Status.OK)]


def check_fixture_bytes(entry: dict[str, Any], response: Response) -> Finding:
    """The hash contract. This is the check the whole product rests on."""
    if response.status != 200:  # noqa: PLR2004
        return Finding(entry["path"], Status.STATUS, str(response.status))
    digest = hashlib.sha256(response.body).hexdigest()
    if digest != entry["sha256"]:
        return Finding(
            entry["path"],
            Status.HASH_MISMATCH,
            f"served {digest[:12]} != manifest {entry['sha256'][:12]}",
        )
    return Finding(entry["path"], Status.OK)


def smallest_per_format(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One fixture per format: smallest by bytes, ties broken by path (docs/12 §4)."""
    chosen: dict[str, dict[str, Any]] = {}
    for entry in sorted(entries, key=lambda e: (e["bytes"], e["path"])):
        fmt = entry["path"].split("/", 1)[0]
        chosen.setdefault(fmt, entry)
    return [chosen[fmt] for fmt in sorted(chosen)]
