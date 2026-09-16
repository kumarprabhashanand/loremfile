"""Internal links resolve to a built key or a fixture; external ones stay on the allow-list."""

from __future__ import annotations

from pathlib import Path

from loremfile.site import checks


def test_every_link_resolves(
    pages: dict[str, str], site_keys: dict[str, Path], fixture_paths: set[str]
) -> None:
    problems = [
        problem
        for key, text in pages.items()
        for problem in checks.link_problems(key, text, set(site_keys), fixture_paths)
    ]
    assert problems == []
