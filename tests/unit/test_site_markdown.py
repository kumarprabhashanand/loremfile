"""The site's Markdown: no raw HTML, one H1 from the template, and a link policy (docs/07 §4)."""

from __future__ import annotations

import pytest

from loremfile.site import markdown

REPOSITORY = "https://github.com/kumarprabhashanand/loremfile"


@pytest.mark.parametrize(
    ("href", "source", "expected"),
    [
        ("https://loremfile.dev/png", None, "/png"),
        ("#section", None, "#section"),
        ("/docs/faq", None, "/docs/faq"),
        ("mailto:hello@loremfile.dev", None, "mailto:hello@loremfile.dev"),
        (
            "https://creativecommons.org/publicdomain/zero/1.0/",
            None,
            "https://creativecommons.org/publicdomain/zero/1.0/",
        ),
        (
            "../../issues/new?template=fixture-request.yml",
            "CONTRIBUTING.md",
            f"{REPOSITORY}/issues/new?template=fixture-request.yml",
        ),
        (
            "docs/05-fixture-catalog.md",
            "CONTRIBUTING.md",
            f"{REPOSITORY}/blob/main/docs/05-fixture-catalog.md",
        ),
        ("//example.com/x", None, None),
        ("https://example.com/x", None, None),
        ("relative.md", None, None),
        ("javascript:alert(1)", None, None),
    ],
)
def test_where_a_link_may_point(href: str, source: str | None, expected: str | None) -> None:
    assert markdown.resolve_link(href, source=source) == expected


def test_a_dropped_link_keeps_its_text() -> None:
    html = markdown.render("See [the spec](https://example.com/spec).")
    assert "<a" not in html
    assert "the spec" in html


def test_raw_html_is_escaped_not_passed_through() -> None:
    html = markdown.render("<script>alert(1)</script>\n\nText <b>bold</b>.")
    assert "<script>" not in html and "<b>" not in html
    assert "&lt;script&gt;" in html


def test_a_body_never_has_an_h1_and_headings_get_unique_ids() -> None:
    html = markdown.render("# Title\n\n## Getting started\n\n## Getting started\n")
    assert "<h1" not in html
    assert '<h2 id="title">' in html
    assert 'id="getting-started"' in html and 'id="getting-started-2"' in html


def test_tables_scroll_inside_a_wrapper() -> None:
    html = markdown.render("| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert '<div class="table-wrap"><table>' in html and "</table></div>" in html


def test_a_leading_title_is_split_off_for_the_template() -> None:
    assert markdown.strip_title("# 03 — HTTP Contract\n\nBody.\n") == (
        "03 — HTTP Contract",
        "Body.\n",
    )
    assert markdown.strip_title("Body.\n") == (None, "Body.\n")
