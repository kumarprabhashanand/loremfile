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
import http.client
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

#: The only host this client talks to.
BASE_URL = "https://loremfile.dev/"

#: Injected by this project's tests so they never touch production. Loopback only.
OVERRIDE = "LOREMFILE_BASE_URL"
LOOPBACK = ("http://127.0.0.1:", "http://localhost:", "http://[::1]:")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: The published rate limit is 30 requests a second per client; one file at a time with a
#: pause between them is well under it, and a 429 is answered with patience.
PAUSE_SECONDS = 0.5
BACKOFF_SECONDS = (2, 4, 8)
TIMEOUT_SECONDS = 300
USER_AGENT = "loremfile-client"

#: Read and hashed a megabyte at a time, so a 100 MB fixture costs a megabyte of memory.
CHUNK_BYTES = 1024 * 1024


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
    if not _is_loopback(override):
        raise Refused(
            f"{OVERRIDE} accepts a loopback address only, so that this project's tests can "
            f"run without touching production; {override!r} is not one. There is no way to "
            "point this client at another host, by design."
        )
    return override if override.endswith("/") else override + "/"


def _is_loopback(value: str) -> bool:
    """The prefix and the parsed host must agree: a prefix alone accepts a URL whose loopback
    address is only the userinfo in front of an `@`, and whose real host is somewhere else."""
    if not value.startswith(LOOPBACK):
        return False
    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        return False
    return (
        parts.scheme == "http"
        and parts.hostname in LOOPBACK_HOSTS
        and parts.username is None
        and parts.password is None
    )


def _open(path: str) -> http.client.HTTPResponse:
    """An open response, retrying only a 429 — our own rate limit asking for patience.

    The retry is here, around opening, because that is where a 429 arrives. A stream
    that fails halfway is not retried: the caller would have to decide what to do with
    the bytes it already has, and this client's answer to a half-file is to delete it.
    """
    url = base_url() + path.lstrip("/")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    for pause in (*BACKOFF_SECONDS, None):
        try:
            response = urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS)  # noqa: S310
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and pause is not None:  # noqa: PLR2004 - the HTTP status
                time.sleep(pause)
                continue
            raise Unreachable(f"{url} answered {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise Unreachable(f"{url} could not be read: {exc.reason}") from exc
        if response.geturl().split("/")[2] != url.split("/")[2]:
            response.close()
            raise Refused(f"{url} redirected off loremfile.dev, which is never followed")
        # urlopen is typed as returning Any for non-HTTP schemes; this client only ever
        # opens http(s), which `base_url` is the single gate for. A cast rather than an
        # assert: `python -O` strips asserts, and shipped code should not depend on a
        # statement that may not be there.
        return cast("http.client.HTTPResponse", response)
    raise Unreachable(f"{url} is still answering 429")


def fetch(path: str) -> bytes:
    """The whole body at once. For the manifest, which is JSON and has to be parsed."""
    with _open(path) as response:
        return bytes(response.read())


def stream(path: str) -> Iterator[bytes]:
    """The body in chunks, for fixtures — which run to 100 MB.

    Reading one of those into memory to hash it would be 100 MB of a CI container's
    often 512 MB, for no benefit: sha256 is happy to be fed a chunk at a time.
    """
    with _open(path) as response:
        while chunk := response.read(CHUNK_BYTES):
            yield bytes(chunk)


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
    """Fetch one fixture, hashing as it arrives, and put it at its path only if it matches.

    The bytes go to a temporary file **in the destination directory**, not to memory and
    not to the system temporary directory: the first would cost 100 MB of RAM for the
    largest fixtures, and the second could be on another filesystem, where the final move
    would be a copy rather than a rename. `Path.replace` within one directory is atomic,
    so a reader of that directory sees either no file or the whole verified one.

    The guarantee is unchanged: nothing unverified is ever at the published path. What is
    new is that nothing unverified survives anywhere — the temporary file is removed on a
    mismatch, on an interrupted download, and on any other failure.
    """
    destination = target(dest, entry["path"])
    if destination.exists() and not force:
        return Result(entry["path"], "skipped", "already here; --force overwrites")
    destination.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    written = 0
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed by the `with` below
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".part", delete=False
    )
    partial = Path(handle.name)
    try:
        with handle:
            for chunk in stream(entry["path"]):
                digest.update(chunk)
                written += handle.write(chunk)
        if digest.hexdigest() != entry["sha256"]:
            raise Mismatch(
                f"{entry['path']}: downloaded sha256 {digest.hexdigest()}, "
                f"the manifest says {entry['sha256']}"
            )
        partial.replace(destination)
    finally:
        # A no-op once the rename has happened, and the whole point otherwise.
        partial.unlink(missing_ok=True)
    return Result(entry["path"], "written", f"{written:,} bytes")


def _sha256_of(file: Path) -> str:
    """A file's hash, read a chunk at a time as `download` reads the network."""
    digest = hashlib.sha256()
    with file.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def verify(entry: dict[str, Any], dest: Path) -> Result:
    """Check a fixture already on disk against the published manifest."""
    destination = target(dest, entry["path"])
    if not destination.is_file():
        return Result(entry["path"], "missing", f"not in {dest}")
    digest = _sha256_of(destination)
    if digest != entry["sha256"]:
        expected = str(entry["sha256"])[:12]
        return Result(entry["path"], "changed", f"sha256 {digest[:12]}, expected {expected}")
    return Result(entry["path"], "ok", f"{destination.stat().st_size:,} bytes")
