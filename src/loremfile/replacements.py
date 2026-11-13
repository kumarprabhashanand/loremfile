"""Sample-file URLs that fail for a plain client, and the command that re-reads them.

`site/content/replacements.yaml` is the list and the /replacements page is built from it. A
reading is only worth writing down if it was taken the way a plain client takes it: no browser
headers, redirects followed, the certificate checked. `observe` does that, `classify` names what
it saw, and `check` compares each row with a fresh reading so the monthly pass (docs/11 §3) can
delete the rows that work again and correct the ones that fail differently.

Nothing here runs from a test with a real host: `observe` takes the opener as a parameter.
"""

from __future__ import annotations

import mimetypes
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from loremfile import config

#: What a row can say, and what each means to someone who tried the URL.
KINDS = ("status", "tls", "not-the-file", "no-cors")
#: A page on another origin asking for the file: servers that decide by `Origin` need one.
PROBE_ORIGIN = "https://example.org"
TIMEOUT_S = 25
HTTP_ERROR = 400
BODY_BYTES = 4096


@dataclass(frozen=True)
class Observation:
    """What a plain client saw: a status and headers, or the reason it saw none."""

    status: int | None = None
    content_type: str = ""
    allow_origin: str | None = None
    error: str | None = None  # "tls", or "network: ..."


@dataclass(frozen=True)
class Reading:
    url: str
    kind: str  # one of KINDS, "works" or "unreadable"
    status: int | None
    detail: str


def load(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """The date the list was last read and its rows, each validated against KINDS."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = data.get("entries") or []
    if not rows or not data.get("checked"):
        raise ValueError(f"{path} needs a 'checked' date and at least one entry")
    for row in rows:
        if row.get("kind") not in KINDS:
            raise ValueError(f"{row.get('url')}: kind must be one of {', '.join(KINDS)}")
        if not str(row.get("url", "")).startswith("https://"):
            raise ValueError(f"{row.get('url')}: a row names an https URL")
    return str(data["checked"]), rows


def observe(url: str, *, opener: Callable[..., Any] | None = None) -> Observation:
    """One plain GET: our own agent, a foreign Origin, redirects followed, TLS verified."""
    request = urllib.request.Request(  # noqa: S310 - https URLs from a reviewed list
        url, headers={"User-Agent": config.VERIFY_USER_AGENT, "Origin": PROBE_ORIGIN}
    )
    open_url = opener or urllib.request.build_opener().open
    try:
        with open_url(request, timeout=TIMEOUT_S) as response:
            response.read(BODY_BYTES)
            return Observation(
                status=response.status,
                content_type=response.headers.get("Content-Type", ""),
                allow_origin=response.headers.get("Access-Control-Allow-Origin"),
            )
    except urllib.error.HTTPError as exc:
        return Observation(status=exc.code, content_type=exc.headers.get("Content-Type", ""))
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            return Observation(error="tls")
        return Observation(error=f"network: {reason}")
    except (TimeoutError, OSError) as exc:
        return Observation(error=f"network: {exc}")


def classify(url: str, seen: Observation) -> Reading:
    """Name what a plain client saw, in the vocabulary of KINDS."""
    if seen.error == "tls":
        return Reading(url, "tls", None, "the certificate fails verification")
    if seen.error or seen.status is None:
        return Reading(url, "unreadable", None, seen.error or "no response")
    if seen.status >= HTTP_ERROR:
        return Reading(url, "status", seen.status, f"{seen.status}")
    wanted = mimetypes.guess_type(urlparse(url).path)[0]
    got = seen.content_type.split(";")[0].strip().lower()
    if wanted and got == "text/html" and wanted != "text/html":
        return Reading(
            url, "not-the-file", seen.status, f"{seen.status}, {got} for a {wanted} name"
        )
    if seen.allow_origin is None:
        return Reading(
            url, "no-cors", seen.status, f"{seen.status}, no Access-Control-Allow-Origin"
        )
    return Reading(url, "works", seen.status, f"{seen.status}, {got}, CORS open")


def matches(row: dict[str, Any], reading: Reading) -> bool:
    """The row still says what a plain client sees: the same kind, and the same status if it
    names one."""
    if reading.kind != row["kind"]:
        return False
    return row.get("status") in (None, reading.status) or row["kind"] == "tls"


def check(
    rows: list[dict[str, Any]], *, opener: Callable[..., Any] | None = None
) -> list[tuple[dict[str, Any], Reading, bool]]:
    """Every row with a fresh reading and whether the row still stands."""
    out = []
    for row in rows:
        reading = classify(row["url"], observe(row["url"], opener=opener))
        out.append((row, reading, matches(row, reading)))
    return out
