"""Every page parses, has one H1, a title, a description, lang, a canonical link and the mark."""

from __future__ import annotations

from loremfile.site import checks


def test_every_page_is_well_formed(pages: dict[str, str]) -> None:
    assert [
        problem for key, text in pages.items() for problem in checks.page_problems(key, text)
    ] == []
