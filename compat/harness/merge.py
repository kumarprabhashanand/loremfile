"""Combine one run's parts into `results/`: sorted keys, no timestamps, one file per format.

A partial run must not publish (docs/07 §8): a file that did not fetch, or whose bytes
did not match, is `not-run` in every cell; more than three such files and nothing is written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import AGENT, MAX_FAILED_FILES, VERSION, scope


class RunFailed(Exception):
    """The run is not fit to commit."""


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def runtime_versions(config: dict[str, Any]) -> list[tuple[str, str]]:
    """(runtime, version) in runtimes.yaml's order, versions ascending."""
    return [
        (r["id"], v) for r in config["runtime_list"] for v in sorted(r["versions"], key=version_key)
    ]


def not_run(detail: str) -> dict[str, str]:
    return {"outcome": "not-run", "detail": detail}


def role(file: dict[str, Any], fmt: str) -> str:
    if file["kind"] == "ordinary":
        return "ordinary"
    return "intended" if file["intended"] == fmt else "also_valid_as"


def expectation(file: dict[str, Any], fmt: str, config: dict[str, Any]) -> dict[str, Any]:
    names = set(config["scope"]["properties"][fmt]) | ({"has_header"} if fmt == "csv" else set())
    return {k: v for k, v in sorted(file["props"].items()) if k in names}


def merge(
    config: dict[str, Any],
    manifest: dict[str, Any],
    fetch_report: dict[str, Any],
    parts: list[dict[str, Any]],
    *,
    date: str,
    run_id: str = "",
) -> dict[str, Any]:
    """{'_run': document, '<format>': document, ...}; raises RunFailed on a run not to commit."""
    files, skipped = scope.corpus(manifest, config)
    fetched = fetch_report.get("files", {})
    failed = {
        f["path"]: fetched.get(f["path"], {}).get("reason", "no fetch report")
        for f in files
        if not fetched.get(f["path"], {}).get("ok")
    }
    if len(failed) > MAX_FAILED_FILES:
        raise RunFailed(
            f"{len(failed)} files did not fetch or did not match the manifest "
            f"(more than {MAX_FAILED_FILES}); this run is not committed: {sorted(failed)[:6]}"
        )
    by_runtime = {(p["runtime"], p["version"]): p for p in parts}
    versions = runtime_versions(config)
    documents: dict[str, Any] = {}
    for fmt in config["scope"]["formats"]:
        readers = [r for r in config["readers"] if fmt in r["formats"]]
        rows = []
        for file in files:
            if fmt not in file["targets"]:
                continue
            cells: dict[str, dict[str, Any]] = {}
            for reader in sorted(readers, key=lambda r: r["id"]):
                per: dict[str, Any] = {}
                for runtime, version in versions:
                    if runtime != reader["runtime"]:
                        continue
                    part = by_runtime.get((runtime, version))
                    key = f"{reader['id']}|{file['path']}"
                    if file["path"] in failed:
                        cell = not_run(f"the file did not fetch: {failed[file['path']]}")
                    elif part is None:
                        cell = not_run("the runtime job did not report")
                    elif "setup_error" in part:
                        cell = not_run(f"the runtime could not be set up: {part['setup_error']}")
                    else:
                        cell = part["cells"].get(key) or not_run("no result for this cell")
                    per[f"{runtime}-{version}"] = cell
                cells[reader["id"]] = per
            rows.append(
                {
                    "path": file["path"],
                    "url": file["url"],
                    "bytes": file["bytes"],
                    "sha256": file["sha256"],
                    "kind": file["kind"],
                    "role": role(file, fmt),
                    "edge_outcome": file["edge_outcome"],
                    "expect": expectation(file, fmt, config),
                    "cells": cells,
                }
            )
        controls: dict[str, Any] = {}
        for reader in readers:
            controls[reader["id"]] = {
                f"{rt}-{v}": (by_runtime[(rt, v)]["controls"].get(reader["id"], {}))
                for rt, v in versions
                if rt == reader["runtime"] and (rt, v) in by_runtime
            }
        documents[fmt] = {
            "format": fmt,
            "readers": sorted(
                ({k: r[k] for k in ("id", "runtime", "module", "docs", "props")} for r in readers),
                key=lambda r: r["id"],
            ),
            "no_reader": sorted(
                rt for rt, formats in config["no_reader"].items() if fmt in formats
            ),
            "runtimes": [f"{rt}-{v}" for rt, v in versions],
            "controls": controls,
            "files": rows,
            "skipped": [
                {"path": f["path"], "bytes": f["bytes"], "reason": "over the size limit"}
                for f in skipped
                if fmt in f["targets"]
            ],
        }
    documents["_run"] = {
        "agent": AGENT,
        "catalog_version": manifest["catalog_version"],
        "date": date,
        "failed_files": dict(sorted(failed.items())),
        "harness": VERSION,
        "run_id": run_id,
        "runtimes": {
            f"{rt}-{v}": (
                {"resolved": by_runtime[(rt, v)].get("resolved")}
                if (rt, v) in by_runtime and "setup_error" not in by_runtime[(rt, v)]
                else {
                    "resolved": None,
                    "not_run": by_runtime.get((rt, v), {}).get("setup_error", "no report"),
                }
            )
            for rt, v in versions
        },
    }
    return documents


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def write(documents: dict[str, Any], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, document in documents.items():
        (out / f"{name}.json").write_text(render(document), encoding="utf-8")
