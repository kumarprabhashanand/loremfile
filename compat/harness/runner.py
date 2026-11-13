"""Run every reader of one runtime version over the fetched files: one process per cell.

The adapter contract (compat/README.md): it prints exactly one JSON object and exits 0, and
anything else is `crashes`. The harness decides `reads` or `differs` itself, by comparing the
properties an adapter reports with the manifest's.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import scope
from .compare import compared, differences

ERROR_LIMIT = 200
Command = list[str]


def adapter_command(runtime: str, compat_dir: Path, work: Path) -> Command:
    """The command prefix that runs this runtime's adapter; builds it first where it compiles."""
    if runtime == "python":
        return [sys.executable, "-I", str(compat_dir / "adapters" / "python" / "adapter.py")]
    if runtime == "go":
        binary = work / "adapter-go"
        source = compat_dir / "adapters" / "go" / "adapter.go"
        build = subprocess.run(
            ["go", "build", "-o", str(binary), str(source)],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "CGO_ENABLED": "0"},
        )
        if build.returncode != 0:
            raise RuntimeError(f"go build failed: {build.stderr.strip()[:ERROR_LIMIT]}")
        return [str(binary)]
    raise RuntimeError(f"no adapter for runtime {runtime!r}")


def resolved_version(runtime: str) -> str:
    if runtime == "python":
        return platform.python_version()
    if runtime == "go":
        out = subprocess.run(["go", "version"], capture_output=True, text=True, check=True).stdout
        return out.split()[2].removeprefix("go")
    raise RuntimeError(f"no version probe for runtime {runtime!r}")


def call(
    command: Command, reader_id: str, path: Path, flags: list[str], timeout: float, cwd: Path
) -> dict[str, Any]:
    """One adapter process. Whatever it does, the answer is one of the contract's three
    outcomes or `crashes`, with what happened as `detail`."""
    try:
        done = subprocess.run(
            [*command, reader_id, str(path), *flags],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return {"outcome": "crashes", "detail": f"no result within {timeout:g} seconds"}
    except OSError as error:
        return {"outcome": "crashes", "detail": f"could not start: {str(error)[:ERROR_LIMIT]}"}
    return contract(done)


def contract(done: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """The adapter's answer if it kept the contract, `crashes` and why if it did not."""
    detail = ""
    answer: Any = None
    if done.returncode != 0:
        line = (done.stderr.strip().splitlines() or [""])[-1][:ERROR_LIMIT]
        detail = f"exit status {done.returncode}: {line}".strip(": ")
    else:
        try:
            answer = json.loads(done.stdout)
        except ValueError:
            detail = "printed no JSON result"
    if not detail and not (
        isinstance(answer, dict) and answer.get("outcome") in ("reads", "refuses", "no-reader")
    ):
        detail = "printed a result outside the contract"
    if not detail and answer["outcome"] == "reads" and not isinstance(answer.get("props"), dict):
        detail = "reads without props"
    return {"outcome": "crashes", "detail": detail} if detail else dict(answer)


def judge(
    answer: dict[str, Any], file: dict[str, Any], reader: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    """The cell: the answer, with `reads` turned into `differs` where a property disagrees."""
    if answer["outcome"] == "refuses":
        return {
            "outcome": "refuses",
            "error_type": str(answer.get("error_type", ""))[:ERROR_LIMIT],
            "error": str(answer.get("error", ""))[:ERROR_LIMIT],
        }
    if answer["outcome"] != "reads":
        return {k: v for k, v in answer.items() if k in ("outcome", "detail")}
    fmt = scope.role_format(file, reader)
    reported = answer["props"]
    cell: dict[str, Any] = {"outcome": "reads", "props": reported}
    found = differences(fmt, reported, file["props"], config["scope"]["tolerance"])
    if found:
        cell["outcome"] = "differs"
        cell["differs"] = found
    cell["compared"] = compared(fmt, reported, file["props"])
    return cell


def flags_for(file: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if file.get("password"):
        flags += ["--password", file["password"]]
    if file.get("delimiter"):
        flags += ["--delimiter", file["delimiter"]]
    return flags


def negative_control(source: Path, kind: str, target: Path) -> Path:
    """The file a reader must not read as it reads the control: empty, or cut in half."""
    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    target.write_bytes(b"" if kind == "zero-byte" else data[: len(data) // 2])
    return target


def slug(reader_id: str) -> str:
    return reader_id.replace("/", "_")


def check_controls(
    command: Command,
    reader: dict[str, Any],
    cells: dict[str, dict[str, Any]],
    files: dict[str, dict[str, Any]],
    work: Path,
    timeout: float,
    cwd: Path,
) -> dict[str, str]:
    """Two controls per control file: the reader reads it, and does not read its broken twin.

    "Does not read" means the answer is not `reads`, or reads properties other than the intact
    file's: a reader that reports the same thing for an empty file as for a real one is not
    reading. A control that misses makes the whole reader `not-run` (the caller does that).
    """
    result: dict[str, str] = {}
    for control in reader["controls"]:
        path = control["reads"]
        key = f"{reader['id']}|{path}"
        intact = cells.get(key)
        file = files.get(path)
        if intact is None or file is None:
            result[f"reads:{path}"] = "missed: the control file was not run"
            result[f"{control['must_not']}:{path}"] = "missed: the control file was not run"
            continue
        result[f"reads:{path}"] = (
            "ok" if intact["outcome"] == "reads" else f"missed: {intact['outcome']}"
        )
        broken = negative_control(
            files[path]["local"],
            control["must_not"],
            work / "controls" / slug(reader["id"]) / f"{control['must_not']}-{Path(path).name}",
        )
        answer = call(command, reader["id"], broken, flags_for(file), timeout, cwd)
        also_read = answer["outcome"] == "reads" and answer["props"] == intact.get("props")
        result[f"{control['must_not']}:{path}"] = (
            "missed: reads it as the intact file" if also_read else "ok"
        )
    return result


def run_runtime(
    config: dict[str, Any],
    files: list[dict[str, Any]],
    work: Path,
    runtime: str,
    version: str,
    *,
    command: Command | None = None,
    progress: Callable[[str], None] = lambda _line: None,
) -> dict[str, Any]:
    """Every cell of one runtime version, and its controls: the part `merge` combines."""
    timeout = float(config["scope"]["timeout_seconds"])
    compat_dir = scope.COMPAT_DIR
    # Absolute, because each adapter runs in its own empty directory: a relative path to the
    # file would name nothing there, and every control would miss (the first CI run did).
    work = work.resolve()
    cwd = work / "cwd"
    cwd.mkdir(parents=True, exist_ok=True)
    part: dict[str, Any] = {"runtime": runtime, "version": version, "cells": {}, "controls": {}}
    try:
        command = command if command is not None else adapter_command(runtime, compat_dir, work)
        part["resolved"] = resolved_version(runtime)
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        part["setup_error"] = str(error)[:ERROR_LIMIT]
        return part
    here = [r for r in config["readers"] if r["runtime"] == runtime]
    by_path = {f["path"]: {**f, "local": work / "files" / f["path"]} for f in files}
    for file in sorted(files, key=lambda f: f["path"]):
        for reader in scope.readers_for(file, config):
            if reader["runtime"] != runtime:
                continue
            progress(f"{reader['id']} {file['path']}")
            answer = call(
                command, reader["id"], by_path[file["path"]]["local"], flags_for(file), timeout, cwd
            )
            part["cells"][f"{reader['id']}|{file['path']}"] = judge(answer, file, reader, config)
    for reader in here:
        part["controls"][reader["id"]] = check_controls(
            command, reader, part["cells"], by_path, work, timeout, cwd
        )
        if any(v != "ok" for v in part["controls"][reader["id"]].values()):
            for key in part["cells"]:
                if key.startswith(reader["id"] + "|"):
                    part["cells"][key] = {"outcome": "not-run", "detail": "a control missed"}
    return part
