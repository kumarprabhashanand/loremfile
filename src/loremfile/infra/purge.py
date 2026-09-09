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
)

#: Discovery files and the root, purged by exact URL.
SITE_FILES = (
    "",
    "index.html",
    "manifest.json",
    "sha256sums.txt",
    "formats.json",
    "llms.txt",
    "robots.txt",
    "sitemap.xml",
    "security.txt",
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

    Format landing pages are purged in both their forms, because ADR-006 stores them as
    two keys (`/pdf` and `/pdf/index.html`) and a stale copy of either is a stale page.
    """
    files = [f"https://{SITE_HOST}/{name}" for name in SITE_FILES]
    for fmt in sorted(formats):
        files.append(f"https://{SITE_HOST}/{fmt}")
        files.append(f"https://{SITE_HOST}/{fmt}/")
        files.append(f"https://{SITE_HOST}/{fmt}/index.json")
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
