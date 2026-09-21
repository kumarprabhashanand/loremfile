"""tests/site checks the site `loremfile site build` just wrote (docs/12 §3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loremfile import config
from loremfile.site import routes


@pytest.fixture(scope="session")
def site_dir() -> Path:
    path = config.repo_root() / config.BUILD_DIR / "site"
    if not path.is_dir():
        pytest.fail("build/site/ does not exist: run `loremfile site build` first")
    return path


@pytest.fixture(scope="session")
def site_keys(site_dir: Path) -> dict[str, Path]:
    return routes.site_files(site_dir)


@pytest.fixture(scope="session")
def pages(site_keys: dict[str, Path]) -> dict[str, str]:
    found = {
        key: path.read_text(encoding="utf-8")
        for key, path in site_keys.items()
        if routes.is_page(key)
    }
    assert len(found) >= 60, "empty-set control: the build must have produced the pages"
    return found


@pytest.fixture(scope="session")
def fixture_paths() -> set[str]:
    return {entry["path"] for entry in json.loads(config.manifest_path().read_text())["fixtures"]}
