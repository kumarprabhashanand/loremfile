"""Hold committed results to the manifest and the reader list.

The checks a test and the `check` command share.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import OUTCOMES, scope
from .merge import runtime_versions


def problems(results: Path, config: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    """Every way the files in `results` fail to match what the corpus and readers require."""
    found: list[str] = []
    run_file = results / "_run.json"
    if not run_file.is_file():
        return [f"{run_file}: missing"]
    run = json.loads(run_file.read_text(encoding="utf-8"))
    found += [
        f"_run.json has no {key}"
        for key in ("agent", "catalog_version", "date", "harness", "run_id", "runtimes")
        if key not in run
    ]
    files, skipped = scope.corpus(manifest, config)
    for fmt in config["scope"]["formats"]:
        path = results / f"{fmt}.json"
        if not path.is_file():
            found.append(f"{fmt}.json: missing")
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        found += format_problems(fmt, document, files, skipped, config, manifest)
    return found


def format_problems(
    fmt: str,
    document: dict[str, Any],
    files: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    config: dict[str, Any],
    manifest: dict[str, Any],
) -> list[str]:
    found: list[str] = []
    readers = [r for r in config["readers"] if fmt in r["formats"]]
    if document.get("format") != fmt:
        found.append(f"{fmt}.json: format is {document.get('format')!r}")
    if [r["id"] for r in document.get("readers", [])] != sorted(r["id"] for r in readers):
        found.append(f"{fmt}.json: readers differ from readers.yaml")
    rows = {row["path"]: row for row in document.get("files", [])}
    wanted = {f["path"] for f in files if fmt in f["targets"]}
    found += [f"{fmt}.json: no row for in-scope {p}" for p in sorted(wanted - rows.keys())]
    found += [
        f"{fmt}.json: row for {p}, which is not in scope" for p in sorted(rows.keys() - wanted)
    ]
    listed = {s["path"] for s in document.get("skipped", [])}
    want_skipped = {f["path"] for f in skipped if fmt in f["targets"]}
    if listed != want_skipped:
        found.append(
            f"{fmt}.json: skipped files are {sorted(listed)}, expected {sorted(want_skipped)}"
        )
    by_path = {e["path"]: e for e in manifest["fixtures"]}
    versions = runtime_versions(config)
    for path, row in rows.items():
        entry = by_path.get(path)
        if entry is None:
            found.append(f"{fmt}.json: {path} is not in the manifest")
        elif (row["sha256"], row["bytes"]) != (entry["sha256"], entry["bytes"]):
            found.append(f"{fmt}.json: {path} does not match the manifest's bytes")
        file = next(f for f in files if f["path"] == path)
        applies = {r["id"] for r in scope.readers_for(file, config) if fmt in r["formats"]}
        if set(row["cells"]) != applies:
            have, want = sorted(row["cells"]), sorted(applies)
            found.append(f"{fmt}.json: {path} has cells for {have}, expected {want}")
        if row.get("no_reader") != scope.no_reader_for(file, config):
            found.append(f"{fmt}.json: {path} names the wrong runtimes as having no reader")
        for reader in readers:
            if reader["id"] not in applies:
                continue
            cells = row["cells"].get(reader["id"], {})
            for runtime, version in versions:
                if runtime != reader["runtime"]:
                    continue
                cell = cells.get(f"{runtime}-{version}")
                where = f"{fmt}.json {path} {reader['id']} {runtime}-{version}"
                found += [f"{where}: no cell"] if cell is None else cell_problems(where, cell)
    return found


def cell_problems(where: str, cell: dict[str, Any]) -> list[str]:
    outcome = cell.get("outcome")
    rules = {
        "reads": (
            not isinstance(cell.get("props"), dict) or bool(cell.get("differs")),
            "needs props and no differences",
        ),
        "differs": (
            not isinstance(cell.get("props"), dict) or not cell.get("differs"),
            "needs props and a difference",
        ),
        "refuses": (not cell.get("error"), "needs an error"),
        "crashes": (not cell.get("detail"), "needs a detail"),
        "not-run": (not cell.get("detail"), "needs a detail"),
        "no-reader": (False, ""),
    }
    if outcome not in OUTCOMES:
        return [f"{where}: outcome {outcome!r} is not in the vocabulary"]
    wrong, why = rules[outcome]
    return [f"{where}: {outcome} {why}"] if wrong else []
