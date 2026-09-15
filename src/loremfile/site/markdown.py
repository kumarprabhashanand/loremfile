"""Markdown for the site: CommonMark and tables, no raw HTML, and a link policy (docs/07 §4).

A link survives only if it stays on this site or reaches an allowed host. Anything else keeps
its text and loses its target, so a document can be published without widening the allow-list.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

from loremfile.config import SITE_HOST, SOURCE_URL
from loremfile.site import routes

SLUG = re.compile(r"[^a-z0-9]+")


def strip_title(text: str) -> tuple[str | None, str]:
    """A leading `# Title` line, and the text without it; the template supplies the H1."""
    first, _, rest = text.partition("\n")
    if first.startswith("# "):
        return first[2:].strip(), rest.lstrip("\n")
    return None, text


def resolve_link(href: str, *, source: str | None) -> str | None:
    """Where a link points once published, or None to keep only its text."""
    if href.startswith(("#", "mailto:")) or (href.startswith("/") and not href.startswith("//")):
        return href
    parts = urlsplit(href)
    if parts.scheme in {"http", "https"} and parts.netloc == SITE_HOST:
        return (parts.path or "/") + (f"#{parts.fragment}" if parts.fragment else "")
    if parts.scheme or parts.netloc:
        target = href
    elif source is None:
        return None
    else:
        target = urljoin(f"{SOURCE_URL}/blob/main/{source}", href)
    return target if routes.allowed_external(target) else None


def _link_policy(tokens: list[Token], source: str | None) -> None:
    for token in tokens:
        if token.type != "inline" or not token.children:
            continue
        kept: list[Token] = []
        dropped: list[bool] = []
        for child in token.children:
            if child.type == "link_open":
                target = resolve_link(str(child.attrGet("href") or ""), source=source)
                dropped.append(target is None)
                if target is None:
                    continue
                child.attrSet("href", target)
            elif child.type == "link_close" and dropped.pop():
                continue
            kept.append(child)
        token.children = kept


def _headings(tokens: list[Token]) -> None:
    """One H1 per page belongs to the template, so a body never carries one; h2-h4 get ids."""
    seen: dict[str, int] = {}
    for index, token in enumerate(tokens):
        if token.type not in {"heading_open", "heading_close"}:
            continue
        if token.tag == "h1":
            token.tag = "h2"
        if token.type == "heading_open" and token.tag in {"h2", "h3", "h4"}:
            slug = SLUG.sub("-", tokens[index + 1].content.lower()).strip("-") or "section"
            count = seen.get(slug, 0)
            seen[slug] = count + 1
            token.attrSet("id", slug if count == 0 else f"{slug}-{count + 1}")


def render(text: str, *, source: str | None = None, breaks: bool = False) -> str:
    parser = MarkdownIt("commonmark", {"html": False, "breaks": breaks}).enable("table")
    tokens = parser.parse(text)
    _headings(tokens)
    _link_policy(tokens, source)
    html = str(parser.renderer.render(tokens, parser.options, {}))
    return html.replace("<table>", '<div class="table-wrap"><table>').replace(
        "</table>", "</table></div>"
    )
