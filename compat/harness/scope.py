"""What goes to which reader: the corpus, from the committed manifest and readers.yaml.

`runtimes.yaml` and `readers.yaml` are written as JSON, which YAML accepts, so this module reads
them with the standard library and the site build reads the same bytes with PyYAML.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

COMPAT_DIR = Path(__file__).resolve().parents[1]
ROOT = COMPAT_DIR.parent
ALIAS_GENERATOR = "alias.copy"


def load_json(path: Path) -> Any:  # noqa: ANN401 - whatever the document is
    return json.loads(path.read_text(encoding="utf-8"))


def load_config(compat_dir: Path = COMPAT_DIR) -> dict[str, Any]:
    readers = load_json(compat_dir / "readers.yaml")
    runtimes = load_json(compat_dir / "runtimes.yaml")
    checked = max(r["checked"] for r in runtimes["runtimes"])
    return {**readers, "runtime_list": runtimes["runtimes"], "checked": checked}


def load_manifest(root: Path = ROOT) -> dict[str, Any]:
    manifest: dict[str, Any] = load_json(root / "manifest.json")
    return manifest


def listed(value: Any) -> list[str]:  # noqa: ANN401 - a string, a list or nothing
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value] if isinstance(value, list) else []


def corpus(
    manifest: dict[str, Any], config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(files to run, files skipped for size), sorted by path.

    In scope: an active, non-alias, non-deprecated entry of a format on the list; or an `edge/`
    entry whose `intended_format` or `also_valid_as` is on it (those go to that format's
    readers). Entries over `max_bytes` are skipped and listed, never silently dropped.
    """
    scope = config["scope"]
    formats = set(scope["formats"])
    files: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for entry in sorted(manifest["fixtures"], key=lambda e: e["path"]):
        if (
            entry.get("status", "active") != "active"
            or entry.get("generator") == ALIAS_GENERATOR
            or entry.get("deprecated")
        ):
            continue
        props = entry.get("props", {})
        if entry["format"] == "edge":
            wanted = [*listed(props.get("intended_format")), *listed(props.get("also_valid_as"))]
            targets = [f for f in dict.fromkeys(wanted) if f in formats]
            kind = "edge"
        elif entry["format"] in formats:
            targets, kind = [entry["format"]], "ordinary"
        else:
            continue
        if not targets:
            continue
        record = {
            "path": entry["path"],
            "url": entry["url"],
            "bytes": entry["bytes"],
            "sha256": entry["sha256"],
            "added_in": entry.get("added_in", "1.0.0"),
            "kind": kind,
            "intended": props.get("intended_format") if kind == "edge" else entry["format"],
            "targets": targets,
            "edge_outcome": props.get("outcome") if kind == "edge" else None,
            "password": (entry.get("generator_params") or {}).get("password")
            if props.get("encrypted")
            else None,
            "delimiter": props.get("delimiter") if "csv" in targets else None,
            "props": {k: v for k, v in props.items() if k in expected_names(scope)},
            "route": {k: props.get(k) for k in route_names(config)},
        }
        (skipped if entry["bytes"] > scope["max_bytes"] else files).append(record)
    return files, skipped


def expected_names(scope: dict[str, Any]) -> set[str]:
    names = {name for group in scope["properties"].values() for name in group}
    return names | {"has_header"}


def route_names(config: dict[str, Any]) -> set[str]:
    """The manifest props that decide which readers a file goes to (`when` in readers.yaml)."""
    names: set[str] = set()
    for item in [*config["readers"], *config["scope"].get("no_reader_when", [])]:
        names |= set(item.get("when", {}))
    return names


def matches(file: dict[str, Any], when: dict[str, list[Any]]) -> bool:
    """True when every named manifest prop of the file is one of the values listed."""
    return all(file["route"].get(name) in values for name, values in when.items())


def readers_for(file: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    """The readers a file goes to, in id order: those of any format it targets, and, for a
    reader that names a `when`, only the files whose manifest props say so. A reader that
    takes uncompressed tar is not handed a gzip stream and then blamed for it."""
    targets = set(file["targets"])
    found = [
        r
        for r in config["readers"]
        if targets & set(r["formats"]) and matches(file, r.get("when", {}))
    ]
    return sorted(found, key=lambda r: r["id"])


def no_reader_for(file: dict[str, Any], config: dict[str, Any]) -> list[str]:
    """Runtimes whose standard library has no reader for this particular file (`no_reader_when`),
    as opposed to none for its whole format (`no_reader`)."""
    return sorted(
        {
            rule["runtime"]
            for rule in config["scope"].get("no_reader_when", [])
            if rule["format"] in file["targets"] and matches(file, rule["when"])
        }
    )


def role_format(file: dict[str, Any], reader: dict[str, Any]) -> str:
    """The format this reader reads this file as: its first target the reader reads."""
    return str(next(f for f in file["targets"] if f in reader["formats"]))


def no_reader_formats(config: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = config["no_reader"]
    return result
