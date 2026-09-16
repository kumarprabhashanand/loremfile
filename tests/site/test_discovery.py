"""llms files, sitemap, security.txt, robots and the legal-page exclusions (docs/04 §5-§8)."""

from __future__ import annotations

from pathlib import Path

from loremfile.site import checks, legal, routes


def test_the_discovery_files_follow_their_specifications(
    site_dir: Path, site_keys: dict[str, Path]
) -> None:
    assert checks.discovery_problems(site_dir, set(site_keys)) == []


def test_pull_request_builds_keep_the_placeholders_in_the_two_legal_pages_only(
    site_dir: Path,
) -> None:
    assert sorted(legal.leftover_placeholders(site_dir)) == sorted(routes.LEGAL_KEYS)
