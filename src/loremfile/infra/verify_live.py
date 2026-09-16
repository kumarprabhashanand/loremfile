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

import datetime as dt
import hashlib
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from loremfile.config import FIXTURE_CACHE_CONTROL, SITE_HOST
from loremfile.site import routes


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
    RDAP_EXPIRY = "rdap_expiry"
    TLS_EXPIRY = "tls_expiry"
    SECURITY_TXT_EXPIRY = "security_txt_expiry"


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


#: `daily` GETs and hashes every fixture below this; `full` hashes everything. The line
#: exists because hashing the whole catalog daily is not a daily job. **`daily` does not
#: yet sample above it**: docs/12 §4 specifies a 5 % rotating sample of larger fixtures,
#: and this comment used to claim it existed. It does not — a fixture of 1 MB or more is
#: never hashed by `daily`, only by `full`. Recorded in docs/12 §4 with the other checks
#: that table promised and this module does not perform.
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


# --- expiry (daily and full) ----------------------------------------------------------

#: IANA's RDAP bootstrap (data.iana.org/rdap/dns.json) names this server for `.dev`.
RDAP_URL = f"https://pubapi.registry.google/rdap/domain/{SITE_HOST}"
#: docs/11 §7.1 and RISK-05. Nothing else on this account warns before the domain lapses.
RDAP_WARN_DAYS = 45
#: Cloudflare renews edge certificates well before this; a closer date means renewal failed.
TLS_WARN_DAYS = 14


def registration_expiry(url: str = RDAP_URL) -> dt.datetime:
    """The domain's `expiration` event from the registry's RDAP record."""
    request = urllib.request.Request(url, headers={"Accept": "application/rdap+json"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as raw:  # noqa: S310 - fixed https URL
        document = json.loads(raw.read())
    for event in document.get("events") or []:
        if event.get("eventAction") == "expiration":
            return dt.datetime.fromisoformat(str(event["eventDate"]).replace("Z", "+00:00"))
    raise ValueError("the RDAP record has no expiration event")


def parse_not_after(value: str) -> dt.datetime:
    """`notAfter` as `ssl.getpeercert` reports it, e.g. `Dec  7 06:23:04 2026 GMT`."""
    return dt.datetime.fromtimestamp(ssl.cert_time_to_seconds(value), tz=dt.UTC)


def certificate_expiry(host: str = SITE_HOST) -> dt.datetime:
    context = ssl.create_default_context()
    with (
        socket.create_connection((host, 443), timeout=30) as sock,
        context.wrap_socket(sock, server_hostname=host) as tls,
    ):
        certificate = tls.getpeercert()
    return parse_not_after(str((certificate or {})["notAfter"]))


def check_expiry(
    name: str,
    status: Status,
    read: Callable[[], dt.datetime],
    *,
    warn_days: int,
    now: dt.datetime,
) -> Finding:
    """A date that cannot be read is a finding too: it is the only warning there is."""
    try:
        expires = read()
    except (OSError, ValueError, KeyError) as exc:
        return Finding(name, status, f"could not read the expiry: {exc}")
    days = (expires - now).days
    shown = f"expires {expires:%Y-%m-%d}, in {days} days"
    if days < warn_days:
        return Finding(name, status, f"{shown} (warns under {warn_days})")
    return Finding(name, Status.OK, shown)


def expiry_findings(now: dt.datetime | None = None) -> list[Finding]:
    moment = now or dt.datetime.now(dt.UTC)
    return [
        check_expiry(
            f"domain:{SITE_HOST}",
            Status.RDAP_EXPIRY,
            registration_expiry,
            warn_days=RDAP_WARN_DAYS,
            now=moment,
        ),
        check_expiry(
            f"tls:{SITE_HOST}",
            Status.TLS_EXPIRY,
            certificate_expiry,
            warn_days=TLS_WARN_DAYS,
            now=moment,
        ),
        check_expiry(
            "/.well-known/security.txt",
            Status.SECURITY_TXT_EXPIRY,
            security_txt_expiry,
            warn_days=SECURITY_TXT_WARN_DAYS,
            now=moment,
        ),
    ]


# --- the site (docs/09 §3.3) ------------------------------------------------------------

SECURITY_TXT_WARN_DAYS = 30
#: docs/03 §4.3, as the `site_pages_headers` rule (H3) sets them on every page.
EXPECTED_PAGE_HEADERS: dict[str, str] = {
    "content-security-policy": routes.SITE_CSP,
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-content-type-options": "nosniff",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}
#: Set only by the fixture rule (H1). On a page they mean its `/index.html` exclusion or its
#: extension test no longer holds (docs/09 §3.2).
FIXTURE_ONLY_HEADERS = ("cross-origin-resource-policy", "timing-allow-origin")
LEGAL_META = f'<meta name="robots" content="{routes.LEGAL_ROBOTS}">'.encode()


def security_txt_expiry() -> dt.datetime:
    response = fetch("/.well-known/security.txt", method="GET")
    if response.status != 200:  # noqa: PLR2004
        raise ValueError(f"/.well-known/security.txt answered {response.status}")
    match = re.search(rb"^Expires: (\S+?)\r?$", response.body, re.M)
    if match is None:
        raise ValueError("security.txt has no Expires field")
    return dt.datetime.fromisoformat(match.group(1).decode().replace("Z", "+00:00"))


def site_hashes(site_dir: Path) -> dict[str, str]:
    return {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in routes.site_files(site_dir).items()
    }


def check_site_key(key: str, digest: str, response: Response) -> list[Finding]:
    """One site key against the rebuild: the defacement check."""
    path = routes.public_path(key)
    if response.status == 0:
        return [Finding(path, Status.TIMEOUT, "no response")]
    if response.status == 404:  # noqa: PLR2004
        return [Finding(path, Status.MISSING_OBJECT, "404")]
    if response.status != 200:  # noqa: PLR2004
        return [Finding(path, Status.STATUS, str(response.status))]
    findings: list[Finding] = []
    served_type, wanted = response.header("content-type"), routes.content_type(key)
    if served_type != wanted:
        findings.append(
            Finding(path, Status.CONTENT_TYPE_MISMATCH, f"{served_type!r} != {wanted!r}")
        )
    served = hashlib.sha256(response.body).hexdigest()
    if served != digest:
        findings.append(
            Finding(path, Status.HASH_MISMATCH, f"served {served[:12]} != built {digest[:12]}")
        )
    return findings or [Finding(path, Status.OK)]


def check_page_headers(path: str, response: Response, *, legal: bool) -> list[Finding]:
    if response.status != 200:  # noqa: PLR2004 - the byte check reports it
        return []
    findings: list[Finding] = []
    for name, expected in EXPECTED_PAGE_HEADERS.items():
        served = response.header(name)
        if served != expected:
            status = Status.HEADER_VALUE if served else Status.HEADER_MISSING
            findings.append(Finding(path, status, f"{name}: {served!r} != {expected!r}"))
    stray = [name for name in FIXTURE_ONLY_HEADERS if response.header(name)]
    if stray:
        findings.append(Finding(path, Status.HEADER_VALUE, f"fixture headers on a page: {stray}"))
    robots = response.header("x-robots-tag")
    wanted = routes.LEGAL_ROBOTS if legal else ""
    if robots != wanted:
        findings.append(
            Finding(path, Status.HEADER_VALUE, f"x-robots-tag: {robots!r} != {wanted!r}")
        )
    if legal and LEGAL_META not in response.body:
        findings.append(Finding(path, Status.HEADER_MISSING, "robots meta tag (ADR-028)"))
    return findings or [Finding(path, Status.OK)]


def header_branch_findings(hashes: dict[str, str], responses: dict[str, Response]) -> list[Finding]:
    """The header rules' branches on real pages: `/`, a format page with and without its
    slash, the legal pages, and a per-format index (docs/09 §3.2, ADR-032)."""
    prefix = f"{routes.FORMAT_INDEX_DIR}/"
    formats = sorted(key[len(prefix) : -len(".json")] for key in hashes if key.startswith(prefix))
    findings: list[Finding] = []
    for key in ("index.html", *formats[:1], *routes.LEGAL_KEYS):
        if key in responses:
            findings += check_page_headers(
                routes.public_path(key), responses[key], legal=key in routes.LEGAL_KEYS
            )
    for key in (*formats[:1], "docs", *routes.LEGAL_KEYS):
        if key not in hashes:
            continue
        alias = f"/{key}/"
        response = fetch(alias, method="GET")
        if response.status != 200:  # noqa: PLR2004
            findings.append(Finding(alias, Status.STATUS, f"{response.status} (ADR-032 rewrite)"))
            continue
        findings += check_page_headers(alias, response, legal=key in routes.LEGAL_KEYS)
        if hashlib.sha256(response.body).hexdigest() != hashes[key]:
            findings.append(
                Finding(alias, Status.HASH_MISMATCH, f"is not the {key} page (ADR-032)")
            )
    index = responses.get(routes.format_index_key(formats[0])) if formats else None
    if index is not None and index.status == 200:  # noqa: PLR2004
        path = routes.public_path(routes.format_index_key(formats[0]))
        if index.header("x-robots-tag") != "noindex" or index.header("content-security-policy"):
            findings.append(Finding(path, Status.HEADER_VALUE, "not served with the file headers"))
    return findings


def site_findings(
    site_dir: Path, *, retry_after: int = 0, sleep: Callable[[float], None] = time.sleep
) -> list[Finding]:
    """Every site key against this job's rebuild, never against the bucket (docs/09 §3.3)."""
    hashes = site_hashes(site_dir)
    if not hashes:
        return [Finding(str(site_dir), Status.MISSING_OBJECT, "no built site; nothing compared")]
    responses = {key: fetch(routes.public_path(key), method="GET") for key in hashes}
    results = {key: check_site_key(key, hashes[key], responses[key]) for key in hashes}
    failing = [
        key for key, found in results.items() if any(f.status is not Status.OK for f in found)
    ]
    if failing and retry_after:
        sleep(retry_after)  # a merge's deploy may still be publishing
        for key in failing:
            responses[key] = fetch(routes.public_path(key), method="GET")
            results[key] = check_site_key(key, hashes[key], responses[key])
    findings = [finding for key in sorted(results) for finding in results[key]]
    return findings + header_branch_findings(hashes, responses)
