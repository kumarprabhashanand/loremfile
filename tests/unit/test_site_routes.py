"""ADR-032: which key a URL reaches, mirrored from the committed edge rules."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from loremfile import config
from loremfile.site import routes

ROOT = Path(__file__).resolve().parents[2]
DAY = "public, max-age=86400"


@pytest.mark.parametrize(
    ("path", "key"),
    [
        ("/", "index.html"),
        ("/pdf", "pdf"),
        ("/pdf/", "pdf"),
        ("/docs/", "docs"),
        ("/docs/faq/", "docs/faq"),
        ("/pdf/index.json", "_formats/pdf.json"),
        ("/pdf/a4-3pages.pdf", "pdf/a4-3pages.pdf"),
        ("/hls/720p-10s/index.m3u8", "hls/720p-10s/index.m3u8"),
        ("/_probe/dir/", "_probe/dir/index.html"),
        ("/_probe/index.json", "_probe/index.json"),
        ("/.well-known/security.txt", ".well-known/security.txt"),
        ("/.well-known/agent-skills/index.json", ".well-known/agent-skills/index.json"),
    ],
)
def test_a_request_path_reaches_the_key_the_edge_serves(path: str, key: str) -> None:
    assert routes.key_for(path) == key


def test_every_kind_of_key_is_reached_by_its_public_path_and_its_disk_name() -> None:
    for key in (
        "index.html",
        "pdf",
        "docs",
        "docs/faq",
        "legal/imprint",
        "_formats/pdf.json",
        "_formats/pdf.md",
        "_formats/testing/uploads.md",
        "assets/site.0123456789ab.css",
        ".well-known/security.txt",
    ):
        assert routes.key_for(routes.public_path(key)) == key
        assert routes.key_of(routes.disk_path(key)) == key
    assert routes.disk_path("docs") == "docs.html"
    assert routes.disk_path("index.html") == "index.html"


def test_the_mirror_matches_the_committed_rewrite_rules() -> None:
    document = json.loads((ROOT / "infra/rulesets/http_request_transform.json").read_text())
    rules = {rule["ref"]: rule for rule in document["rules"]}
    assert set(rules) == {"root_index", "dir_index", "page_slash", "format_index_json"}

    def target(ref: str) -> str:
        return str(rules[ref]["action_parameters"]["uri"]["path"]["expression"])

    assert 'starts_with(http.request.uri.path, "/_probe/")' in rules["dir_index"]["expression"]
    assert target("page_slash") == "substring(http.request.uri.path, 0, -1)"
    pattern, replacement = '"/*/index.*"', f'"/{routes.FORMAT_INDEX_DIR}/${{1}}.${{2}}"'
    assert target("format_index_json") == (
        f"wildcard_replace(http.request.uri.path, {pattern}, {replacement})"
    )
    for suffix in ("/index.json", "/index.md"):
        clause = f'ends_with(http.request.uri.path, "{suffix}")'
        assert clause in rules["format_index_json"]["expression"]
    for excluded in ("/_", "/.well-known/"):
        clause = f'not starts_with(http.request.uri.path, "{excluded}")'
        assert clause in rules["format_index_json"]["expression"]
        assert routes.key_for(f"{excluded}x/index.json") == f"{excluded[1:]}x/index.json"


def wildcard_replace(source: str, pattern: str, replacement: str) -> str:
    """Cloudflare's function as its reference describes it, written apart from `routes`: the
    whole source must match, each `*` lazily, ignoring case; no match returns the source."""
    regex = "(.*?)".join(re.escape(part) for part in pattern.split("*"))
    found = re.fullmatch(regex, source, re.IGNORECASE | re.DOTALL)
    if not found:
        return source
    return re.sub(r"\$\{(\d)\}", lambda ref: found.group(int(ref.group(1))), replacement)


#: Requests the index rewrite's filter admits, ordinary and awkward: a guide's twin is two
#: segments deep, and a second "/index." or a capital one is where lazy and greedy differ.
INDEX_PATHS = (
    "/pdf/index.json",
    "/pdf/index.md",
    "/testing/uploads/index.md",
    "/a/index.b/index.json",
    "/a/INDEX.x/index.md",
)


WILDCARD_CALL = re.compile(r'wildcard_replace\(http\.request\.uri\.path, "([^"]+)", "([^"]+)"\)')


def disagreements(target: str, mirror: Callable[[str], str]) -> list[tuple[str, str, str]]:
    """(path, the edge's key, the mirror's key) wherever the rewrite and the mirror differ."""
    found = WILDCARD_CALL.fullmatch(target)
    assert found, f"not one wildcard_replace() call: {target}"
    pattern, replacement = found.groups()
    return [
        (path, edge, key)
        for path in INDEX_PATHS
        if (edge := wildcard_replace(path, pattern, replacement)[1:]) != (key := mirror(path))
    ]


def index_rule_target() -> str:
    document = json.loads((ROOT / "infra/rulesets/http_request_transform.json").read_text())
    rule = next(r for r in document["rules"] if r["ref"] == "format_index_json")
    return str(rule["action_parameters"]["uri"]["path"]["expression"])


def test_the_index_rewrite_and_its_mirror_reach_the_same_keys() -> None:
    assert routes.key_for("/pdf/index.md") == f"{routes.FORMAT_INDEX_DIR}/pdf.md"
    assert disagreements(index_rule_target(), routes.key_for) == []


def test_the_rewrite_check_fires_on_a_json_only_rule_and_on_a_greedy_mirror() -> None:
    json_only = index_rule_target().replace('"/*/index.*"', '"/*/index.json"')
    json_only = json_only.replace("${2}", "json")
    assert disagreements(json_only, routes.key_for) == [
        ("/pdf/index.md", "pdf/index.md", "_formats/pdf.md"),
        ("/testing/uploads/index.md", "testing/uploads/index.md", "_formats/testing/uploads.md"),
        ("/a/index.b/index.json", "_formats/a/index.b.json", "_formats/a.b/index.json"),
        ("/a/INDEX.x/index.md", "a/INDEX.x/index.md", "_formats/a.x/index.md"),
    ]

    def greedy(path: str) -> str:
        stem, suffix = path.rsplit("/index.", 1)
        return f"{routes.FORMAT_INDEX_DIR}{stem}.{suffix}"

    assert disagreements(index_rule_target(), greedy) == [
        ("/a/index.b/index.json", "_formats/a.b/index.json", "_formats/a/index.b.json"),
        ("/a/INDEX.x/index.md", "_formats/a.x/index.md", "_formats/a/INDEX.x.md"),
    ]


@pytest.mark.parametrize(
    ("key", "mime", "cache"),
    [
        ("pdf", "text/html; charset=utf-8", config.SITE_CACHE_CONTROL),
        ("index.html", "text/html; charset=utf-8", config.SITE_CACHE_CONTROL),
        ("_formats/pdf.json", "application/json", config.SITE_CACHE_CONTROL),
        ("schema/manifest-v1.json", "application/schema+json", config.ASSET_CACHE_CONTROL),
        ("assets/site.0123456789ab.css", "text/css; charset=utf-8", config.ASSET_CACHE_CONTROL),
        ("assets/og.png", "image/png", DAY),
        ("favicon.ico", "image/x-icon", DAY),
        (".well-known/security.txt", "text/plain; charset=utf-8", DAY),
        ("sitemap.xml", "application/xml", config.SITE_CACHE_CONTROL),
    ],
)
def test_content_type_and_cache_control_follow_docs_02(key: str, mime: str, cache: str) -> None:
    assert routes.content_type(key) == mime
    assert routes.cache_control(key) == cache


def test_a_suffix_with_no_documented_type_is_refused() -> None:
    with pytest.raises(ValueError, match="no content type"):
        routes.content_type("assets/tool.exe")


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://github.com/kumarprabhashanand/loremfile/issues", True),
        ("https://github.com/kumarprabhashanand/loremfile-toolchain", False),
        ("https://github.com/someone/else", False),
        ("https://creativecommons.org/publicdomain/zero/1.0/", True),
        ("http://creativecommons.org/", False),
        ("https://example.com/", False),
    ],
)
def test_the_link_allow_list(url: str, allowed: bool) -> None:
    assert routes.allowed_external(url) is allowed
