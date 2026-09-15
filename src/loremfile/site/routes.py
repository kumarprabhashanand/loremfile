"""Where each site key is served, and with which headers (docs/02 §4, ADR-032).

`key_for` mirrors `infra/rulesets/http_request_transform.json`, so `site serve`,
`verify-live` and the purge reach the same key the edge does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from loremfile.config import (
    ASSET_CACHE_CONTROL,
    BASE_URL,
    OWNER,
    SITE_CACHE_CONTROL,
)

#: docs/03 §4.3, as the `site_pages_headers` rule sets it.
SITE_CSP: Final = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
LEGAL_ROBOTS: Final = "noindex, nofollow, nosnippet"
#: Both edge rules match these exact paths, so the values may live nowhere else (docs/15 M4.1).
LEGAL_KEYS: Final = ("legal/imprint", "legal/privacy")
LEGAL_TWINS: Final = tuple(
    f"{key}{suffix}" for key in LEGAL_KEYS for suffix in (".html", "/index.html")
)
FORMAT_INDEX_DIR: Final = "_formats"
PROBE_PREFIX: Final = "/_probe/"
DAY_CACHE_CONTROL: Final = "public, max-age=86400"
DAY_CACHED: Final = frozenset(
    {
        "favicon.ico",
        "apple-touch-icon.png",
        "assets/og.png",
        "assets/mark.svg",
        ".well-known/security.txt",
    }
)
CONTENT_TYPES: Final = {
    "json": "application/json",
    "txt": "text/plain; charset=utf-8",
    "xml": "application/xml",
    "css": "text/css; charset=utf-8",
    "js": "text/javascript; charset=utf-8",
    "svg": "image/svg+xml",
    "png": "image/png",
    "ico": "image/x-icon",
}
#: The only external hosts a page may link to (docs/07 §4).
ALLOWED_HOSTS: Final = frozenset(
    {"creativecommons.org", "llmstxt.org", "developers.cloudflare.com"}
)


def allowed_external(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False
    if parts.netloc == "github.com":
        repository = f"/{OWNER}/loremfile"
        return parts.path == repository or parts.path.startswith(f"{repository}/")
    return parts.netloc in ALLOWED_HOSTS


def format_index_key(fmt: str) -> str:
    return f"{FORMAT_INDEX_DIR}/{fmt}.json"


def is_page(key: str) -> bool:
    return key == "index.html" or "." not in key.rsplit("/", 1)[-1]


def disk_path(key: str) -> str:
    """Where a key lives under `build/site/`.

    A page key is also a prefix (`docs` and `docs/faq`), and a filesystem cannot hold a file
    and a directory under one name, so every page but the root is stored as `{key}.html`.
    """
    return key if key == "index.html" or not is_page(key) else f"{key}.html"


def key_of(relative: str) -> str:
    return relative.removesuffix(".html") if relative != "index.html" else relative


def site_files(site_dir: Path) -> dict[str, Path]:
    """Key -> file for everything under a built site directory."""
    return {
        key_of(path.relative_to(site_dir).as_posix()): path
        for path in sorted(site_dir.rglob("*"))
        if path.is_file()
    }


def public_path(key: str) -> str:
    if key == "index.html":
        return "/"
    if key.startswith(f"{FORMAT_INDEX_DIR}/") and key.endswith(".json"):
        return f"/{key[len(FORMAT_INDEX_DIR) + 1 : -len('.json')]}/index.json"
    return f"/{key}"


def absolute_url(key: str) -> str:
    return f"{BASE_URL}{public_path(key)[1:]}"


def key_for(path: str) -> str:
    """The key the edge serves for a request path: the four rewrites of docs/08 §5.2."""
    if path == "/":
        return "index.html"
    if path.endswith("/") and path.startswith(PROBE_PREFIX):
        return f"{path[1:]}index.html"
    if path.endswith("/"):
        return path[1:-1]
    if path.endswith("/index.json") and not path.startswith("/_"):
        return f"{FORMAT_INDEX_DIR}{path[: -len('/index.json')]}.json"
    return path[1:]


def content_type(key: str) -> str:
    if is_page(key):
        return "text/html; charset=utf-8"
    if key.startswith("schema/") and key.endswith(".json"):
        return "application/schema+json"
    suffix = key.rsplit(".", 1)[-1]
    if suffix not in CONTENT_TYPES:
        raise ValueError(f"{key}: no content type for .{suffix} (docs/09 §5)")
    return CONTENT_TYPES[suffix]


def cache_control(key: str) -> str:
    if key in DAY_CACHED:
        return DAY_CACHE_CONTROL
    if key.startswith(("assets/", "schema/")):
        return ASSET_CACHE_CONTROL
    return SITE_CACHE_CONTROL
