"""Tell IndexNow which site pages a deploy changed (docs/04 §12).

Cloudflare's Crawler Hints already sends IndexNow signals, inferred from cache misses. This
names the pages a deploy actually wrote, read from the site upload's own report, after
`verify-live` has seen them served. Bing, Yandex, Seznam, Naver, Yep, the Internet Archive
and Amazon take part; Google does not.

Three things are never sent. Fixtures: they are files, not pages, and the site upload never
writes one. The two legal pages: they are kept out of every index (ADR-028), and announcing
them would contradict their `noindex` header and the WAF rule that refuses AI agents on them.
And more than `MAX_URLS`: a deploy that changed more announces the home page and the sitemap.

Nothing here can fail a deploy. Any answer is logged and the command exits 0; an engine
refusing a notification changes nothing about what was published.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

from loremfile.config import INDEXNOW_KEY, SITE_HOST
from loremfile.site import routes

ENDPOINT: Final = "https://api.indexnow.org/indexnow"
MAX_URLS: Final = 100
#: 200 is "URL submitted successfully", 202 "URL received. IndexNow key validation pending."
ACCEPTED: Final = frozenset({200, 202})
TIMEOUT_SECONDS: Final = 30

Post = Callable[[str, bytes], int]


def changed_pages(uploaded: Iterable[str]) -> list[str]:
    """The absolute URLs of the uploaded keys that are pages, minus the legal ones."""
    legal = {*routes.LEGAL_KEYS, *routes.LEGAL_TWINS}
    return [
        routes.absolute_url(key)
        for key in sorted(set(uploaded))
        if routes.is_page(key) and key not in legal
    ]


def never_legal(urls: list[str]) -> list[str]:
    """The last filter before anything is sent: nothing under `/legal/`, whatever built the
    list. A second layer for the one exclusion that would break a published promise."""
    return [url for url in urls if not urlsplit(url).path.startswith("/legal/")]


def url_list(pages: list[str]) -> list[str]:
    """`pages`, or the home page and the sitemap when there are more than `MAX_URLS`."""
    if len(pages) > MAX_URLS:
        return [routes.absolute_url("index.html"), routes.absolute_url("sitemap.xml")]
    return pages


def payload(urls: list[str]) -> dict[str, Any]:
    return {
        "host": SITE_HOST,
        "key": INDEXNOW_KEY,
        "keyLocation": routes.absolute_url(routes.INDEXNOW_KEY_FILE),
        "urlList": urls,
    }


def _post(url: str, body: bytes) -> int:
    request = urllib.request.Request(  # noqa: S310 - a fixed https endpoint
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


@dataclass(frozen=True)
class Outcome:
    submitted: list[str]
    status: int | None
    detail: str

    @property
    def accepted(self) -> bool:
        return self.status in ACCEPTED


def announce(uploaded: Iterable[str], *, post: Post | None = None) -> Outcome:
    """Submit the changed pages. Never raises: every outcome is something to log.

    `post` is looked up when called, not bound as a default, so the transport a caller or a
    test installs as `_post` is the one used.
    """
    send = post or _post
    pages = changed_pages(uploaded)
    if not pages:
        return Outcome([], None, "no page changed; nothing to announce")
    urls = never_legal(url_list(pages))
    capped = "" if urls == pages else f" ({len(pages)} pages changed, over {MAX_URLS})"
    try:
        status = send(ENDPOINT, json.dumps(payload(urls)).encode("utf-8"))
    except (OSError, ValueError) as exc:
        return Outcome(urls, None, f"not sent: {exc}")
    verdict = "accepted" if status in ACCEPTED else "refused"
    return Outcome(urls, status, f"{len(urls)} URL(s){capped}: HTTP {status}, {verdict}")


def uploaded_keys(report: dict[str, Any]) -> list[str]:
    """The site keys an `upload --site --json` report says were written.

    A dry run writes nothing, so it announces nothing; neither does a report whose upload
    wrote fewer keys than it planned, because then which ones landed is not known.
    """
    summary = report.get("summary") or {}
    planned = [item["path"] for item in report.get("items") or [] if item.get("status") == "upload"]
    if summary.get("mode") != "site" or summary.get("dry_run") or not report.get("ok"):
        return []
    if summary.get("written") != len(planned):
        return []
    return planned
