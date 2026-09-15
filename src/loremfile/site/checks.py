"""Checks on a built site (docs/07 §4 step 5, docs/12 §3).

`site build` runs them before anything can be published, and `tests/site` runs them in CI.
Each returns problems as text; an empty list is a pass.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import gzip
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import html5lib
from html5lib.html5parser import ParseError

from loremfile.config import SITE_HOST
from loremfile.site import routes

ATTRIBUTE = re.compile(r'\s(href|src|content)="([^"]*)"')
H1 = re.compile(r"<h1[\s>]")
JSONLD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
LOC = re.compile(r"<loc>([^<]+)</loc>")
URL_FIELDS = frozenset({"url", "contentUrl", "license", "codeRepository", "item"})
PAGE_GZIP_LIMIT = 60_000
CSS_LIMIT = 15_000
JS_LIMIT = 10_000
LEGAL_PATHS = tuple(f"/{key}" for key in routes.LEGAL_KEYS)


def _jsonld(text: str) -> list[Any]:
    return [json.loads(block.replace("<\\/", "</")) for block in JSONLD.findall(text)]


def _urls_in(value: Any) -> list[str]:  # noqa: ANN401 - walks decoded JSON
    if isinstance(value, dict):
        found = [str(v) for k, v in value.items() if k in URL_FIELDS and isinstance(v, str)]
        return found + [url for v in value.values() for url in _urls_in(v)]
    if isinstance(value, list):
        return [url for item in value for url in _urls_in(item)]
    return []


def page_problems(key: str, text: str) -> list[str]:
    problems: list[str] = []
    try:
        html5lib.HTMLParser(strict=True, namespaceHTMLElements=False).parse(text)
    except ParseError as exc:
        problems.append(f"{key}: HTML does not parse cleanly: {exc}")
    headings = len(H1.findall(text))
    if headings != 1:
        problems.append(f"{key}: {headings} <h1> elements, not one")
    required = {
        "a title": re.search(r"<title>[^<]+</title>", text),
        "a meta description": '<meta name="description" content="' in text,
        'lang="en"': '<html lang="en">' in text,
        "a canonical link": '<link rel="canonical" href="' in text,
        "the inline mark": '<svg aria-hidden="true"' in text,
    }
    problems += [f"{key}: has no {what}" for what, present in required.items() if not present]
    if "<object" in text or "<iframe" in text:
        problems.append(f"{key}: uses <object> or <iframe>; the mark is inlined (docs/07 §2)")
    size = len(gzip.compress(text.encode("utf-8"), mtime=0))
    if size > PAGE_GZIP_LIMIT:
        problems.append(f"{key}: {size:,} bytes gzipped, over {PAGE_GZIP_LIMIT:,}")
    legal = key in routes.LEGAL_KEYS
    if legal != (f'<meta name="robots" content="{routes.LEGAL_ROBOTS}">' in text):
        problems.append(f"{key}: robots meta tag {'missing' if legal else 'present'} (ADR-028)")
    try:
        blocks = _jsonld(text)
    except ValueError as exc:
        return [*problems, f"{key}: JSON-LD is not valid JSON: {exc}"]
    if legal and blocks:
        problems.append(f"{key}: carries JSON-LD, which ADR-028 forbids on this page")
    return problems


def url_problem(key: str, url: str, keys: set[str], fixtures: set[str]) -> str | None:
    if url.startswith(("#", "mailto:")):
        return None
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.netloc != SITE_HOST:
        return (
            None if routes.allowed_external(url) else f"{key}: link outside the allow-list: {url}"
        )
    if parts.scheme not in {"", "https"} or (not parts.scheme and not url.startswith("/")):
        return f"{key}: link that is neither https nor site-relative: {url}"
    target = routes.key_for(parts.path or "/")
    if target in keys or target in fixtures:
        return None
    return f"{key}: {url} resolves to no key or fixture"


def link_problems(key: str, text: str, keys: set[str], fixtures: set[str]) -> list[str]:
    urls = [
        value
        for name, value in ATTRIBUTE.findall(text)
        if name != "content" or value.startswith(("http:", "https:"))
    ]
    with contextlib.suppress(ValueError):  # page_problems reports invalid JSON-LD
        urls += [url for block in _jsonld(text) for url in _urls_in(block)]
    found = (url_problem(key, url, keys, fixtures) for url in urls)
    return [problem for problem in found if problem]


def _llms_problems(name: str, text: str) -> list[str]:
    problems: list[str] = []
    if not text.startswith("# loremfile.dev\n\n> "):
        problems.append(f"{name}: no H1 and summary blockquote (llmstxt.org layout)")
    for heading in ("## How to use", "## Formats", "## Rules"):
        if f"\n{heading}\n" not in text:
            problems.append(f"{name}: no {heading!r} section")
    if any(path in text for path in LEGAL_PATHS):
        problems.append(f"{name}: lists a legal page that names the operator (ADR-028)")
    return problems


def _sitemap_problems(text: str, keys: set[str]) -> list[str]:
    locs = LOC.findall(text)
    problems = [] if locs else ["sitemap.xml: lists no URL"]
    for loc in locs:
        path = urlsplit(loc).path
        if routes.key_for(path) not in keys:
            problems.append(f"sitemap.xml: {loc} resolves to no key")
        if path in LEGAL_PATHS:
            problems.append(f"sitemap.xml: lists {path} (ADR-028)")
    return problems


def _security_txt_problems(text: str) -> list[str]:
    problems = [
        f".well-known/security.txt: no {field.strip()} field"
        for field in ("Contact: ", "Expires: ", "Canonical: ", "Policy: ")
        if f"\n{field}" not in f"\n{text}"
    ]
    expires = re.search(r"^Expires: (\S+)$", text, re.M)
    if expires:
        try:
            dt.datetime.fromisoformat(expires.group(1).replace("Z", "+00:00"))
        except ValueError:
            problems.append(
                f".well-known/security.txt: Expires is not RFC 3339: {expires.group(1)}"
            )
    return problems


def _asset_problems(site_dir: Path, keys: set[str]) -> list[str]:
    problems: list[str] = []
    for suffix, limit in ((".css", CSS_LIMIT), (".js", JS_LIMIT)):
        for key in sorted(keys):
            if key.startswith("assets/") and key.endswith(suffix):
                size = (site_dir / routes.disk_path(key)).stat().st_size
                if size > limit:
                    problems.append(f"{key}: {size:,} bytes, over {limit:,}")
    return problems


def discovery_problems(site_dir: Path, keys: set[str]) -> list[str]:
    def read(key: str) -> str:
        path = site_dir / routes.disk_path(key)
        return path.read_text(encoding="utf-8") if key in keys else ""

    problems = [*_llms_problems("llms.txt", read("llms.txt"))]
    problems += _llms_problems("llms-full.txt", read("llms-full.txt"))
    problems += _sitemap_problems(read("sitemap.xml"), keys)
    if any(key.removeprefix("legal/") in read("search-index.json") for key in routes.LEGAL_KEYS):
        problems.append("search-index.json: mentions a legal page (ADR-028)")
    problems += _security_txt_problems(read(".well-known/security.txt"))
    problems += [
        f"{key}: the legal page is missing" for key in routes.LEGAL_KEYS if key not in keys
    ]
    problems += [f"{key}: twin of a legal page" for key in routes.LEGAL_TWINS if key in keys]
    return problems + _asset_problems(site_dir, keys)


def all_problems(site_dir: Path, fixtures: set[str]) -> list[str]:
    files = routes.site_files(site_dir)
    keys = set(files)
    problems: list[str] = []
    for key, path in files.items():
        if routes.is_page(key):
            text = path.read_text(encoding="utf-8")
            problems += page_problems(key, text)
            problems += link_problems(key, text, keys, fixtures)
    return problems + discovery_problems(site_dir, keys)
