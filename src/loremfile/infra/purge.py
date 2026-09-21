"""Cache purge (docs/09 §6). Zone-scoped, batched, and deliberately narrow.

**Fixtures are never purged.** Their bytes never change, so a purge could only ever
throw away a cache entry that was still correct — costing an R2 read to refetch
identical bytes. The one exception is a takedown, where the removed URL must stop being
served (`docs/11` §7.8), and that path names the URL explicitly rather than sweeping a
prefix.

The batch limit is the Free plan's per-request maximum of 100 operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loremfile.config import SITE_HOST
from loremfile.infra.cloudflare_api import Client

#: Free plan: at most this many prefixes/files per purge request.
BATCH = 100

#: Prefixes the site owns and rewrites on every deploy.
SITE_PREFIXES = (
    f"{SITE_HOST}/docs/",
    f"{SITE_HOST}/legal/",
    f"{SITE_HOST}/assets/",
    f"{SITE_HOST}/.well-known/agent-skills/",
)

#: Discovery files and the root, purged by exact URL.
SITE_FILES = (
    "",
    "index.html",
    "formats",
    "changelog",
    "status",
    "docs",
    "docs/",
    "legal",
    "legal/",
    "manifest.json",
    "sha256sums.txt",
    "formats.json",
    "search-index.json",
    "llms.txt",
    "llms-full.txt",
    "sitemap.xml",
    "robots.txt",
    ".well-known/security.txt",
    ".well-known/api-catalog",
    "favicon.ico",
    "apple-touch-icon.png",
)

#: Never purged, and the reason is not tidiness: these bytes are immutable, so an entry
#: in cache is always still correct, and dropping it costs an R2 read to refetch the
#: identical object. `schema/` is versioned and equally immutable.
NEVER_PURGE_PREFIXES = ("schema/",)


class PurgeError(RuntimeError):
    """A purge request failed."""


@dataclass
class PurgeReport:
    batches: int = 0
    prefixes: int = 0
    files: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        return f"  {self.prefixes} prefix(es), {self.files} file(s) in {self.batches} batch(es)"


def site_targets(formats: list[str]) -> tuple[list[str], list[str]]:
    """(prefixes, absolute URLs) for `purge --site`.

    Every URL that reaches a format page or index is purged: `/pdf` and `/pdf/` share one key,
    and `/pdf/index.json` is rewritten to `_formats/pdf.json` (ADR-032). Which URL a cache
    entry is filed under is not documented, so both forms go.
    """
    files = [f"https://{SITE_HOST}/{name}" for name in SITE_FILES]
    for fmt in sorted(formats):
        files.append(f"https://{SITE_HOST}/{fmt}")
        files.append(f"https://{SITE_HOST}/{fmt}/")
        files.append(f"https://{SITE_HOST}/{fmt}/index.json")
        files.append(f"https://{SITE_HOST}/_formats/{fmt}.json")
    return list(SITE_PREFIXES), files


def _batched(items: list[str]) -> list[list[str]]:
    return [items[i : i + BATCH] for i in range(0, len(items), BATCH)]


def purge(client: Client, prefixes: list[str], files: list[str]) -> PurgeReport:
    """Purge by prefix and by URL, in batches the Free plan accepts."""
    report = PurgeReport(prefixes=len(prefixes), files=len(files))
    path = f"/zones/{client.zone_id}/purge_cache"

    for batch in _batched(prefixes):
        report.batches += 1
        response = client.post(path, {"prefixes": batch})
        if not response.ok:
            report.errors.append(f"prefixes {batch[:2]}…: {response.errors}")
    for batch in _batched(files):
        report.batches += 1
        response = client.post(path, {"files": batch})
        if not response.ok:
            report.errors.append(f"files {batch[:2]}…: {response.errors}")
    return report


def purge_restored_urls(client: Client, urls: list[str]) -> PurgeReport:
    """The restore path (`docs/09` §5) — with takedown, the only purges that name fixtures.

    A restored object can be shadowed at the edge: by the 404 cached while it was missing,
    or by the wrong bytes it replaced. Named explicitly, like `purge_removed_url`, so that
    no routine deploy reaches it.
    """
    return purge(client, [], urls)


def purge_removed_url(client: Client, url: str) -> PurgeReport:
    """The takedown path (`docs/11` §7.8) — the only purge that may name a fixture.

    Named explicitly rather than reached through `--site`, so that no routine deploy can
    purge a fixture by accident.
    """
    report = PurgeReport(files=1, batches=1)
    response = client.post(f"/zones/{client.zone_id}/purge_cache", {"files": [url]})
    if not response.ok:
        report.errors.append(f"{url}: {response.errors}")
    return report
