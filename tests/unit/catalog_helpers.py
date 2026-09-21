"""Builders for throwaway catalogs. Plain helpers, not pytest fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

TAGS = ["document", "text", "multi-page", "data", "image", "invalid", "truncated"]


def minimal_fixture(**overrides: Any) -> dict[str, Any]:
    """A fixture row that passes every rule, before overrides are applied."""
    row: dict[str, Any] = {
        "name": "a4-3pages.pdf",
        "phase": 1,
        "generator": "pdf.basic",
        "params": {"pages": 3},
        "description": "A4 portrait, 3 pages of Lorem Ipsum with page numbers.",
        "tags": ["document", "multi-page"],
        "expect": {"pages": 3},
        "size_class": "free",
    }
    row.update(overrides)
    return {k: v for k, v in row.items() if v is not None or k in overrides}


def minimal_format(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "format": "pdf",
        "family": "documents",
        "mime": "application/pdf",
        "description": "Portable Document Format files for viewers and parsers.",
        "seo_title": "Sample PDF files for testing",
        "related": [],
        "fixtures": [minimal_fixture()],
    }
    doc.update(overrides)
    # The real loader injects the owning format into each row before validating
    # (Catalog._load_format); mirror that so a FormatCatalog can be validated directly.
    for row in doc["fixtures"]:
        row.setdefault("format", doc["format"])
    return doc


def write_format(directory: Path, doc: dict[str, Any]) -> Path:
    """Write one catalog/{format}.yaml into a throwaway directory."""
    path = directory / f"{doc['format']}.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path
