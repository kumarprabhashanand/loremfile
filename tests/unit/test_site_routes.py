"""ADR-032: which key a URL reaches, mirrored from the committed edge rules."""

from __future__ import annotations

import json
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
    assert f'"/{routes.FORMAT_INDEX_DIR}"' in target("format_index_json")
    assert f"0, -{len('/index.json')}" in target("format_index_json")
    for excluded in ("/_", "/.well-known/"):
        clause = f'not starts_with(http.request.uri.path, "{excluded}")'
        assert clause in rules["format_index_json"]["expression"]
        assert routes.key_for(f"{excluded}x/index.json") == f"{excluded[1:]}x/index.json"


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
