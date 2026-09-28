"""Fetching fixtures from loremfile.dev, and checking every byte that arrives.

Standard library only, on purpose (the CLI spec): a client whose job is to download a
file and hash it should not ask anyone to resolve a dependency tree, and the smaller the
supply chain the less there is to audit.

The one thing to know about this module: `BASE_URL` is a constant. There is no flag, no
configuration file and no environment variable that points the client at another host —
only a loopback override this project's own tests inject, which is rejected for anything
that is not 127.0.0.1, ::1 or localhost. A mirror flag would contradict the README's
"do not rely on any other mirror", and an override that accepted a public host would be a
way to make `loremfile get` fetch from somewhere else entirely.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

#: The only host this client talks to.
BASE_URL = "https://loremfile.dev/"

#: Injected by this project's tests so they never touch production. Loopback only.
OVERRIDE = "LOREMFILE_BASE_URL"
LOOPBACK = ("http://127.0.0.1:", "http://localhost:", "http://[::1]:")

#: The published rate limit is 30 requests a second per client; one file at a time with a
#: pause between them is well under it, and a 429 is answered with patience.
PAUSE_SECONDS = 0.5
BACKOFF_SECONDS = (2, 4, 8)
TIMEOUT_SECONDS = 300
USER_AGENT = "loremfile-client"


class Refused(Exception):
    """The request was wrong: an unknown path, a bad override, a version that has moved."""


class Unreachable(Exception):
    """loremfile.dev could not be read."""


class Mismatch(Exception):
    """Bytes arrived that are not the bytes the manifest describes."""


def base_url() -> str:
    override = os.environ.get(OVERRIDE, "").strip()
    if not override:
        return BASE_URL
    if not override.startswith(LOOPBACK):
        raise Refused(
            f"{OVERRIDE} accepts a loopback address only, so that this project's tests can "
            f"run without touching production; {override!r} is not one. There is no way to "
            "point this client at another host, by design."
        )
    return override if override.endswith("/") else override + "/"


def fetch(path: str) -> bytes:
    """One GET, retrying only a 429 — our own rate limit asking for patience."""
    url = base_url() + path.lstrip("/")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    for pause in (*BACKOFF_SECONDS, None):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
                if response.geturl().split("/")[2] != url.split("/")[2]:
                    raise Refused(f"{url} redirected off loremfile.dev, which is never followed")
                return bytes(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and pause is not None:  # noqa: PLR2004 - the HTTP status
                time.sleep(pause)
                continue
            raise Unreachable(f"{url} answered {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise Unreachable(f"{url} could not be read: {exc.reason}") from exc
    raise Unreachable(f"{url} is still answering 429")


def manifest(*, catalog_version: str | None = None) -> dict[str, Any]:
    try:
        document = json.loads(fetch("manifest.json"))
    except json.JSONDecodeError as exc:
        raise Unreachable(f"the manifest is not JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise Unreachable("the manifest is not a JSON object")
    published = str(document.get("catalog_version", ""))
    if catalog_version and published != catalog_version:
        raise Refused(f"loremfile.dev publishes catalog {published}, not {catalog_version}")
    return dict(document)


def active(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in document.get("fixtures", []) if e.get("status", "active") == "active"]


def select(
    entries: list[dict[str, Any]],
    *,
    paths: list[str] | None = None,
    formats: list[str] | None = None,
) -> list[dict[str, Any]]:
    """The entries a request names, or `Refused` naming what does not exist."""
    wanted_paths, wanted_formats = set(paths or []), set(formats or [])
    if not wanted_paths and not wanted_formats:
        raise Refused("name at least one path or format")
    by_path = {e["path"]: e for e in entries}
    unknown = sorted(wanted_paths - set(by_path))
    if unknown:
        raise Refused(f"not published: {', '.join(unknown)}")
    published_formats = {e["format"] for e in entries}
    unknown_formats = sorted(wanted_formats - published_formats)
    if unknown_formats:
        raise Refused(f"no such format: {', '.join(unknown_formats)}")
    chosen = {
        e["path"]: e for e in entries if e["path"] in wanted_paths or e["format"] in wanted_formats
    }
    return [chosen[path] for path in sorted(chosen)]


def target(dest: Path, path: str) -> Path:
    """Where a fixture lands, refusing anything that would escape `dest`.

    The paths come from our own manifest, so this is not the day's most likely failure —
    but a client that writes where a downloaded document tells it to is the shape of
    problem this project publishes a fixture about (`edge/zip-directory-traversal-name.zip`).
    """
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise Refused(f"refusing {path!r}: not the shape of a fixture path")
    resolved = (dest / Path(*relative.parts)).resolve()
    if not str(resolved).startswith(str(dest.resolve())):
        raise Refused(f"refusing {path!r}: it would be written outside {dest}")
    return resolved


def pace() -> None:
    """The wait between two downloads. One place, so a test can make it instant and the
    rate manners stay a property of this module rather than of whoever loops."""
    time.sleep(PAUSE_SECONDS)


@dataclass(frozen=True)
class Result:
    """What happened to one fixture."""

    path: str
    status: str  # written | skipped | ok | missing | changed
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"written", "skipped", "ok"}


def download(entry: dict[str, Any], dest: Path, *, force: bool = False) -> Result:
    """Fetch one fixture, hash it, and write it only if the hash is the published one."""
    destination = target(dest, entry["path"])
    if destination.exists() and not force:
        return Result(entry["path"], "skipped", "already here; --force overwrites")
    body = fetch(entry["path"])
    digest = hashlib.sha256(body).hexdigest()
    if digest != entry["sha256"]:
        raise Mismatch(
            f"{entry['path']}: downloaded sha256 {digest}, the manifest says {entry['sha256']}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(body)
    return Result(entry["path"], "written", f"{len(body):,} bytes")


def verify(entry: dict[str, Any], dest: Path) -> Result:
    """Check a fixture already on disk against the published manifest."""
    destination = target(dest, entry["path"])
    if not destination.is_file():
        return Result(entry["path"], "missing", f"not in {dest}")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        expected = str(entry["sha256"])[:12]
        return Result(entry["path"], "changed", f"sha256 {digest[:12]}, expected {expected}")
    return Result(entry["path"], "ok", f"{destination.stat().st_size:,} bytes")
