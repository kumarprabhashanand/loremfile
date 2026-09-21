"""Shared pytest fixtures for the unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from catalog_helpers import TAGS


@pytest.fixture
def catalog_dir(tmp_path: Path) -> Path:
    """An empty catalog directory with the tag vocabulary already in place."""
    directory = tmp_path / "catalog"
    directory.mkdir()
    (directory / "_tags.yaml").write_text(yaml.safe_dump({"tags": TAGS}), encoding="utf-8")
    return directory
