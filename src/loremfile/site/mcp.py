"""The fixture metadata used by the remote MCP transport."""

from __future__ import annotations

import json
from typing import Any

from loremfile.config import BASE_URL
from loremfile.manifest import Manifest, is_alias

MAX_INDEX_BYTES = 150_000
IDENTITY_FIELDS = ("path", "format", "mime", "bytes", "sha256")
OPTIONAL_FIELDS = ("size_class", "added_in")
ROW_FIELDS = (*IDENTITY_FIELDS, *OPTIONAL_FIELDS, "tags", "description")


def fixture_details(entry: dict[str, Any]) -> dict[str, Any]:
    """The fields returned by describe_fixture, with catalog_version held at document level."""
    return {
        **{key: entry[key] for key in IDENTITY_FIELDS},
        **{key: entry.get(key) for key in OPTIONAL_FIELDS},
        "url": f"{BASE_URL}{entry['path']}",
        "tags": entry.get("tags", []),
        "description": entry.get("description", ""),
        "props": entry.get("props"),
    }


def _properties(rows: list[dict[str, Any]]) -> dict[str, Any]:
    # Store common property names once. A row alternates key indexes and values.
    keys: dict[str, int] = {}
    encoded: list[list[Any] | None] = []
    for row in rows:
        props = row["props"]
        values: list[Any] = []
        if props is not None:
            for key, value in props.items():
                values.extend((keys.setdefault(key, len(keys)), value))
        encoded.append(None if props is None else values)
    return {"keys": list(keys), "rows": encoded}


def compact_index(manifest: Manifest) -> bytes:
    """One JSON payload for a list across formats. All columns have the same path order."""
    rows = [
        fixture_details(entry)
        for entry in sorted(manifest.active, key=lambda e: e["path"])
        if not is_alias(entry)
    ]
    columns: dict[str, Any] = {key: [row[key] for row in rows] for key in ROW_FIELDS}
    # Every URL is the shared base and its row's path. Describe reads props from the format index.
    columns.update(url=BASE_URL, props=_properties(rows))
    payload = {"catalog_version": manifest.catalog_version, "fixtures": columns}
    data = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    if len(data) > MAX_INDEX_BYTES:
        raise ValueError(f"MCP fixture index is {len(data)} bytes (limit {MAX_INDEX_BYTES})")
    return data
