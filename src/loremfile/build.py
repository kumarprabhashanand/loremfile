"""Generate fixtures into ``build/fixtures/`` (docs/06 §4 and §5).

Selection, dependency order and the determinism guard live here. What this module does
*not* do is decide whether the bytes are acceptable — that is the validators' job — or
write the manifest, which only ``manifest update`` does.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from loremfile import config
from loremfile.catalog import Catalog, Fixture, Status
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.manifest import Manifest
from loremfile.util.determinism import deterministic

#: Generator modules to import so their @generator decorators run. A family is added
#: here by the milestone that writes it.
GENERATOR_MODULES = ("binary", "text")

#: Format groups for `--group`, used to split the CI matrix (docs/06 §5).
GROUPS: dict[str, frozenset[str]] = {
    "media": frozenset(
        [
            "mp4",
            "webm",
            "mkv",
            "mov",
            "avi",
            "ogv",
            "ts",
            "hls",
            "mp3",
            "wav",
            "flac",
            "ogg",
            "opus",
            "m4a",
            "aac",
            "aiff",
        ]
    ),
    "data": frozenset(
        [
            "csv",
            "tsv",
            "json",
            "ndjson",
            "xml",
            "yaml",
            "toml",
            "ini",
            "parquet",
            "avro",
            "arrow",
            "sqlite",
            "sql",
            "geojson",
            "gpx",
            "kml",
            "kmz",
        ]
    ),
}


class Selection(StrEnum):
    NEW = "new"
    MISSING_IN_BUCKET = "missing-in-bucket"
    ALL = "all"


class BuildError(Exception):
    """A fixture could not be generated. Never partial: the build stops."""


@dataclass
class Built:
    """One generated fixture, before validation."""

    fixture: Fixture
    data: bytes
    sha256: str

    @property
    def path(self) -> str:
        return self.fixture.path


def load_generators() -> None:
    """Import the generator modules so the registry is populated."""
    for name in GENERATOR_MODULES:
        importlib.import_module(f"loremfile.generators.{name}")


def fixtures_dir() -> Path:
    return config.repo_root() / config.BUILD_DIR / "fixtures"


def merge_base_manifest(base_ref: str = "origin/main") -> Manifest:
    """The manifest as of the merge base, for ``--new`` (docs/06 §5).

    A fixture counts as new when its path is absent there. If the ref is unavailable —
    a shallow clone, or a repository with no origin — that is reported rather than
    silently treated as "everything is new", which would rebuild the world.
    """
    root = config.repo_root()
    git = shutil.which("git")
    if git is None:
        raise BuildError("git is not on PATH; --new compares against the merge base")
    try:
        merge_base = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [git, "merge-base", "HEAD", base_ref],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout.strip()
        blob = subprocess.run(  # noqa: S603
            [git, "show", f"{merge_base}:manifest.json"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise BuildError(
            f"cannot read {base_ref} to work out what is new: {exc}. "
            "CI checks out with fetch-depth: 0 for exactly this reason."
        ) from exc
    if blob.returncode != 0:
        return Manifest()  # no manifest at the merge base: everything is new
    data = json.loads(blob.stdout)
    return Manifest(
        catalog_version=data.get("catalog_version", "0.0.0"),
        generated_at=data.get("generated_at"),
        toolchain_image=data.get("toolchain_image"),
        entries=list(data.get("fixtures", [])),
    )


def select(
    catalog: Catalog,
    *,
    selection: Selection = Selection.ALL,
    only: Iterable[str] = (),
    formats: Iterable[str] = (),
    group: str | None = None,
    phase: int | None = None,
    base_ref: str = "origin/main",
) -> list[Fixture]:
    """Work out which fixtures to generate, then add the dependencies they need."""
    chosen = [f for f in catalog.fixtures() if f.status is Status.ACTIVE]

    if selection is Selection.NEW:
        published = set(merge_base_manifest(base_ref).by_path)
        chosen = [f for f in chosen if f.path not in published]
    elif selection is Selection.MISSING_IN_BUCKET:
        raise BuildError(
            "--missing-in-bucket needs the bucket listing, which arrives with the "
            "uploader in M4.3; use --all or --new until then"
        )

    only = set(only)
    formats = set(formats)
    if only:
        chosen = [f for f in chosen if f.path in only]
        unknown = only - {f.path for f in catalog.fixtures()}
        if unknown:
            raise BuildError(f"--only names unknown paths: {', '.join(sorted(unknown))}")
    if formats:
        chosen = [f for f in chosen if f.format in formats]
    if group:
        if group == "other":
            excluded = GROUPS["media"] | GROUPS["data"]
            chosen = [f for f in chosen if f.format not in excluded]
        elif group in GROUPS:
            chosen = [f for f in chosen if f.format in GROUPS[group]]
        else:
            known = ", ".join([*sorted(GROUPS), "other"])
            raise BuildError(f"unknown group '{group}'; known: {known}")
    if phase is not None:
        chosen = [f for f in chosen if f.phase == phase]

    return _with_dependencies(catalog, chosen)


def _with_dependencies(catalog: Catalog, chosen: list[Fixture]) -> list[Fixture]:
    """Add anything the chosen fixtures are built from, in topological order."""
    by_path = catalog.by_path
    ordered: list[Fixture] = []
    seen: set[str] = set()

    def visit(fixture: Fixture) -> None:
        if fixture.path in seen:
            return
        seen.add(fixture.path)
        for dependency in fixture.depends_on:
            visit(by_path[dependency])
        ordered.append(fixture)

    for fixture in sorted(chosen, key=lambda f: f.path):
        visit(fixture)
    return ordered


def generate_one(fixture: Fixture, workdir: Path, resolver: object | None = None) -> Built:
    """Run one generator under the determinism guard and hash what it produced."""
    generator = REGISTRY.get(fixture.generator)
    context = GeneratorContext(path=fixture.path, workdir=workdir)
    if resolver is not None:
        context._dependency = resolver  # type: ignore[assignment]

    with deterministic(context.seed):
        result = generator(context, **fixture.params)

    if isinstance(result, Path):
        data = result.read_bytes()
    elif isinstance(result, bytes):
        data = result
    else:
        raise BuildError(
            f"{fixture.generator} returned {type(result).__name__}; "
            "a generator returns bytes or a Path inside ctx.workdir"
        )
    return Built(fixture=fixture, data=data, sha256=hashlib.sha256(data).hexdigest())


def write(built: Built, into: Path | None = None) -> Path:
    """Write generated bytes to ``build/fixtures/<path>``."""
    target = (into or fixtures_dir()) / built.path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(built.data)
    return target


def build(
    fixtures: list[Fixture],
    *,
    into: Path | None = None,
    keep_bytes: bool = True,
) -> list[Built]:
    """Generate the given fixtures in order, writing each to disk.

    Generation is sequential. The determinism guard patches process-global state
    (``os.urandom``, the clock, the ``random`` module), so two generators cannot run in
    the same process at the same time without corrupting each other's stream. Parallel
    workers arrive with the media generators in M3.6, where the wall-clock cost actually
    matters and process isolation makes the patches safe again.
    """
    load_generators()
    directory = into or fixtures_dir()
    results: list[Built] = []
    produced: dict[str, bytes] = {}

    def resolve(path: str) -> bytes:
        if path in produced:
            return produced[path]
        on_disk = directory / path
        if on_disk.is_file():
            return on_disk.read_bytes()
        raise BuildError(
            f"dependency '{path}' has not been generated and is not published; "
            "the build generates dependencies first, so this is a bug in the ordering"
        )

    for fixture in fixtures:
        try:
            built = generate_one(fixture, workdir=directory.parent / "work", resolver=resolve)
        except BuildError:
            raise
        except Exception as exc:
            raise BuildError(f"{fixture.path}: {type(exc).__name__}: {exc}") from exc
        write(built, directory)
        produced[built.path] = built.data
        results.append(built if keep_bytes else Built(fixture, b"", built.sha256))
    return results


def clean(into: Path | None = None) -> None:
    """Remove the build output. Never touches anything tracked by git."""
    directory = into or fixtures_dir()
    if directory.exists():
        shutil.rmtree(directory)
