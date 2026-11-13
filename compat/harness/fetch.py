"""Fetch each in-scope file from production, once, one at a time, and check its SHA-256.

A file that will not fetch, or whose bytes do not match the committed manifest, is recorded as
failed and is never handed to a reader (docs/07 §8).
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import AGENT

ATTEMPTS = 3
PAUSE = 0.25
CHUNK = 1 << 16


def download(url: str, target: Path, agent: str = AGENT) -> str:
    """Write the body to `target` and return its SHA-256 (hex)."""
    request = urllib.request.Request(url, headers={"User-Agent": agent})
    digest = hashlib.sha256()
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as out:
        while chunk := response.read(CHUNK):
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest()


def fetch_one(
    file: dict[str, Any],
    out: Path,
    *,
    get: Callable[[str, Path], str] = download,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    target = out / file["path"]
    reason = "not attempted"
    for attempt in range(ATTEMPTS):
        try:
            digest = get(file["url"], target)
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            reason = f"{type(error).__name__}: {str(error)[:120]}"
        else:
            if digest == file["sha256"]:
                return {"ok": True}
            reason = f"sha256 {digest} where the manifest has {file['sha256']}"
            target.unlink(missing_ok=True)
            return {"ok": False, "reason": reason}  # wrong bytes do not improve on a retry
        if attempt + 1 < ATTEMPTS:
            sleep(2.0 * (attempt + 1))
    target.unlink(missing_ok=True)
    return {"ok": False, "reason": reason}


def fetch_all(
    files: list[dict[str, Any]],
    out: Path,
    *,
    get: Callable[[str, Path], str] = download,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch every file, one after another, and write `fetch.json` beside them."""
    report: dict[str, Any] = {"agent": AGENT, "files": {}}
    for index, file in enumerate(files):
        report["files"][file["path"]] = fetch_one(file, out / "files", get=get, sleep=sleep)
        if index + 1 < len(files):
            sleep(PAUSE)
    (out / "fetch.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    return report
