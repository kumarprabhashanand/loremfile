"""The `loremfile` pytest fixture: a published file, verified, as a local path.

pytest imports this module through the `pytest11` entry point in every run where the
client is installed, whether or not a test asks for the fixture. So importing it does
nothing: no network, no files, no hooks, no options. All the work happens the first time
a test calls the fixture, and `tests/test_pytest_plugin.py` holds that as a test.

Published files never change at their path, so a cached file and its cached manifest entry
are final. The manifest is fetched again only for a path the cached copy does not list,
and once that cache is filled a suite runs without the network.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from loremfile_client import api


class Files:
    """One session's fetcher over a cache directory. Called with a path, returns a file."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files = root / "files"
        self.cached_manifest = root / "manifest.json"
        self.entries: dict[str, dict[str, Any]] | None = None
        self.refreshed = False
        self.downloads = 0
        self.ready: dict[str, Path] = {}

    def __call__(self, path: str) -> Path:
        if path in self.ready:
            return self.ready[path]
        entry = self.entry(path)
        if not api.verify(entry, self.files).ok:
            self.download(entry)
        local = api.target(self.files, path)
        self.ready[path] = local
        return local

    def entry(self, path: str) -> dict[str, Any]:
        if self.entries is None:
            self.entries = self.read_cached()
        if path not in self.entries and not self.refreshed:
            self.entries = self.refresh()
        # `select` is the CLI's own refusal, so an unknown or removed path reads the same.
        return api.select(list(self.entries.values()), paths=[path])[0]

    def read_cached(self) -> dict[str, dict[str, Any]]:
        try:
            document = json.loads(self.cached_manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {e["path"]: e for e in api.active(document)}

    def refresh(self) -> dict[str, dict[str, Any]]:
        document = api.manifest()
        self.refreshed = True
        try:  # noqa: SIM105 - contextlib would be a new import for one line
            self.write_cached(document)
        except OSError:
            pass  # only the next session pays: this one has the document in memory
        return {e["path"]: e for e in api.active(document)}

    def write_cached(self, document: dict[str, Any]) -> None:
        """Written beside its final name and renamed, so a parallel worker never reads half."""
        self.root.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed by the `with` below
            "w", dir=self.root, suffix=".part", delete=False, encoding="utf-8"
        )
        partial = Path(handle.name)
        try:
            with handle:
                json.dump(document, handle)
            partial.replace(self.cached_manifest)
        finally:
            partial.unlink(missing_ok=True)

    def download(self, entry: dict[str, Any]) -> None:
        if self.downloads:
            api.pace()
        self.downloads += 1
        try:
            api.download(entry, self.files, force=True)
        except OSError:
            # On Windows the final rename fails while another xdist worker has the file
            # open. If that worker already put the verified bytes there, they are ours too.
            if not api.verify(entry, self.files).ok:
                raise


@pytest.fixture(scope="session")
def loremfile(
    pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory
) -> Callable[[str], Path]:
    """loremfile(path) -> Path: a loremfile.dev file, checked against its published SHA-256.

    Cached in .pytest_cache, so each file is downloaded once; `--cache-clear` starts over.
    """
    # `-p no:cacheprovider` removes the attribute itself; a file then lasts one session.
    cache = getattr(pytestconfig, "cache", None)
    root = cache.mkdir("loremfile") if cache is not None else tmp_path_factory.mktemp("loremfile")
    return Files(root)
