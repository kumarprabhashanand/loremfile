"""``manifest.json``, ``sha256sums.txt`` and ``formats.json`` (docs/04, docs/06 §7).

The manifest is the lock file for published bytes. Its central rule: once a path is in
the committed manifest, its ``sha256``, ``bytes`` and ``mime`` can never change. Only
``loremfile manifest update``, run inside the toolchain container, writes this file —
``AGENTS.md`` forbids hand-editing it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loremfile import config
from loremfile.catalog import Fixture

#: Fields frozen once a path is published. Changing any of them is the one thing the
#: whole project promises never to do.
LOCKED_FIELDS = ("sha256", "bytes", "mime")

#: Top-level fields that legitimately change on every run and are therefore excluded
#: from the lock comparison, so a digest bump is a two-line diff (docs/06 §7 step 5).
VOLATILE_TOP_LEVEL = ("generated_at", "toolchain_image")

#: Exactly the fields a tombstone carries (docs/04 §1.5). ``url`` is deliberately absent
#: so clients iterating ``url`` skip removed entries.
TOMBSTONE_FIELDS = (
    "path",
    "format",
    "ext",
    "mime",
    "bytes",
    "sha256",
    "status",
    "removed_at",
    "reason",
    "added_in",
    "description",
    "phase",
)


class LockViolation(Exception):
    """A published entry would change. This is never allowed to merge."""


class ManifestError(Exception):
    """The manifest is structurally wrong."""


@dataclass(frozen=True)
class LockDiff:
    path: str
    fieldname: str
    committed: object
    regenerated: object

    def __str__(self) -> str:
        return (
            f"{self.path}: {self.fieldname} would change from "
            f"{self.committed!r} to {self.regenerated!r}"
        )


@dataclass
class Manifest:
    """The parsed ``manifest.json``."""

    catalog_version: str = "0.0.0"
    generated_at: str | None = None
    toolchain_image: str | None = None
    entries: list[dict[str, Any]] = field(default_factory=list)

    # -- loading and saving -------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> Manifest:
        """Load the committed manifest. A missing file is an empty manifest."""
        path = path or config.manifest_path()
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ManifestError(f"{path} must contain a JSON object")
        return cls(
            catalog_version=data.get("catalog_version", "0.0.0"),
            generated_at=data.get("generated_at"),
            toolchain_image=data.get("toolchain_image"),
            entries=list(data.get("fixtures", [])),
        )

    @property
    def by_path(self) -> dict[str, dict[str, Any]]:
        return {entry["path"]: entry for entry in self.entries}

    @property
    def active(self) -> list[dict[str, Any]]:
        return [e for e in self.entries if e.get("status", "active") == "active"]

    def to_document(self) -> dict[str, Any]:
        """The full top-level object, sorted by path (docs/04 §1.1)."""
        entries = sorted(self.entries, key=lambda e: e["path"])
        active = [e for e in entries if e.get("status", "active") == "active"]
        return {
            "$schema": config.SCHEMA_URL,
            "schema_version": config.SCHEMA_VERSION,
            "catalog_version": self.catalog_version,
            "generated_at": self.generated_at,
            "base_url": config.BASE_URL,
            "license": config.LICENSE,
            "license_url": config.LICENSE_URL,
            "source": config.SOURCE_URL,
            "toolchain_image": self.toolchain_image,
            "count": len(active),
            "total_bytes": sum(e["bytes"] for e in active),
            "formats": sorted({e["format"] for e in active}),
            "fixtures": entries,
        }

    def dumps(self) -> str:
        """Canonical serialisation: 2-space indent, LF, trailing newline, non-ASCII kept."""
        return json.dumps(self.to_document(), indent=2, ensure_ascii=False) + "\n"

    def save(self, path: Path | None = None) -> None:
        path = path or config.manifest_path()
        path.write_text(self.dumps(), encoding="utf-8", newline="\n")

    # -- the rules ----------------------------------------------------------

    def check_lock(self, regenerated: dict[str, dict[str, Any]]) -> list[LockDiff]:
        """Compare regenerated entries against the committed ones (docs/06 §7 step 3).

        ``sha256``, ``bytes`` and ``mime`` must be identical for any path already
        committed. ``props`` are compared only when the bytes actually differ: identical
        bytes with different measured props mean a validator library changed how it
        measures, and the committed props describe the published bytes, so they win.
        Everything else — description, tags, notes, generator, generator_params,
        deprecated, supersededBy — may change freely.
        """
        diffs: list[LockDiff] = []
        committed = self.by_path
        for path, fresh in regenerated.items():
            old = committed.get(path)
            if old is None:
                continue
            for fieldname in LOCKED_FIELDS:
                if fieldname in fresh and old.get(fieldname) != fresh[fieldname]:
                    diffs.append(LockDiff(path, fieldname, old.get(fieldname), fresh[fieldname]))
        return diffs

    def props_warnings(self, regenerated: dict[str, dict[str, Any]]) -> list[str]:
        """Props that differ while the bytes are identical: a warning, not a failure."""
        warnings: list[str] = []
        committed = self.by_path
        for path, fresh in regenerated.items():
            old = committed.get(path)
            if old is None or "props" not in fresh:
                continue
            same_bytes = old.get("sha256") == fresh.get("sha256")
            if same_bytes and old.get("props") != fresh["props"]:
                warnings.append(
                    f"{path}: measured props differ but the bytes are identical; "
                    "keeping the committed props, which describe the published bytes"
                )
        return warnings

    def check_removals(self, catalog_paths: set[str], removable: dict[str, Any]) -> list[str]:
        """A committed path missing from the catalog must be an explicit tombstone.

        ``removable`` maps path -> the catalog's ``removed`` block for entries the
        catalog marks ``status: removed``. Anything else that disappeared is an error:
        silently dropping a published path is how a URL breaks.
        """
        errors: list[str] = []
        for entry in self.entries:
            path = entry["path"]
            if path in catalog_paths or path in removable:
                continue
            if entry.get("status") == "removed":
                continue  # already a tombstone
            errors.append(
                f"{path} is in manifest.json but not in the catalog. Published paths are "
                "never dropped; mark it status: removed with a reason to tombstone it."
            )
        return errors

    def check_total_bytes(self) -> list[str]:
        total = sum(e["bytes"] for e in self.active)
        if total > config.MAX_TOTAL_BYTES:
            return [f"total {total} bytes exceeds MAX_TOTAL_BYTES {config.MAX_TOTAL_BYTES}"]
        return []

    def touch(self, *, changed: bool) -> None:
        """Set the volatile top-level fields (docs/06 §7 step 5).

        ``generated_at`` moves only when something actually changed, so an unchanged
        rebuild produces no diff.
        """
        if changed or self.generated_at is None:
            self.generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.toolchain_image = config.toolchain_digest()


def build_entry(
    fixture: Fixture,
    data: bytes,
    props: dict[str, Any],
    mime: str,
    *,
    added_in: str,
) -> dict[str, Any]:
    """Assemble a manifest entry from a generated fixture and its measured props.

    Field order follows docs/04 §1.2 so the committed JSON reads like the specification.
    ``sha256`` and ``bytes`` are computed here from the actual bytes — never passed in —
    so an entry can never claim a hash the file does not have.
    """
    return {
        "path": fixture.path,
        "url": f"{config.BASE_URL}{fixture.path}",
        "format": fixture.format,
        "ext": fixture.ext,
        "mime": mime,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_class": str(fixture.size_class),
        "phase": fixture.phase,
        "description": fixture.description,
        "tags": list(fixture.tags),
        "edge_case": fixture.edge_case,
        "props": props,
        "generator": fixture.generator,
        "generator_params": dict(fixture.params),
        "added_in": added_in,
        "status": "active",
        "deprecated": False,
        "supersededBy": None,
        **({"notes": fixture.notes} if fixture.notes else {}),
    }


def make_tombstone(entry: dict[str, Any], reason: str, removed_at: str) -> dict[str, Any]:
    """Reduce a published entry to a tombstone (docs/04 §1.5).

    The catalog's nested ``removed.reason``/``removed.removed_at`` become the
    tombstone's top-level ``reason``/``removed_at``.
    """
    source = dict(entry, status="removed", reason=reason, removed_at=removed_at)
    missing = [f for f in TOMBSTONE_FIELDS if f not in source]
    if missing:
        raise ManifestError(f"cannot tombstone {entry.get('path')}: missing {missing}")
    return {fieldname: source[fieldname] for fieldname in TOMBSTONE_FIELDS}


def render_sha256sums(manifest: Manifest) -> str:
    """GNU coreutils format, active fixtures only, sorted by path (docs/04 §2)."""
    lines = [
        f"{entry['sha256']}  {entry['path']}"
        for entry in sorted(manifest.active, key=lambda e: e["path"])
    ]
    return "".join(f"{line}\n" for line in lines)


def render_formats_json(manifest: Manifest, mime_defaults: dict[str, str]) -> str:
    """Per-format counts and byte totals (docs/04 §3). Active fixtures only."""
    formats: dict[str, dict[str, Any]] = {}
    for entry in sorted(manifest.active, key=lambda e: e["path"]):
        fmt = entry["format"]
        row = formats.setdefault(
            fmt,
            {
                "format": fmt,
                "count": 0,
                "total_bytes": 0,
                "url": f"{config.BASE_URL}{fmt}",
                "index": f"{config.BASE_URL}{fmt}/index.json",
                "mime_default": mime_defaults.get(fmt, ""),
            },
        )
        row["count"] += 1
        row["total_bytes"] += entry["bytes"]
    document = {
        "catalog_version": manifest.catalog_version,
        "formats": [formats[key] for key in sorted(formats)],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
