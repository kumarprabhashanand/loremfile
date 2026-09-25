"""Load and validate ``catalog/{format}.yaml`` (docs/06 §3, docs/05 §1).

The YAML is what the pipeline reads. ``docs/05-fixture-catalog.md`` is the prose copy of
the same information; if the two disagree, both are fixed in the same pull request.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Annotated, Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from loremfile import config

# --- grammars (docs/03 §1) -------------------------------------------------

#: A descriptor: lowercase kebab-case, no underscores, no uppercase.
DESCRIPTOR = r"[a-z0-9]+(?:-[a-z0-9]+)*"
#: A fixture name inside a format directory: descriptor plus one or more extensions.
NAME_RE = re.compile(rf"^{DESCRIPTOR}(?:\.[a-z0-9]+)+$")
#: The one nested case. ``hls/{variant}/(index|master).m3u8`` and ``seg-000.ts``.
HLS_NAME_RE = re.compile(
    rf"^{DESCRIPTOR}/(?:index|master)\.m3u8$"
    rf"|^{DESCRIPTOR}/seg-[0-9]{{3}}\.ts$"
)
FORMAT_RE = re.compile(r"^[a-z0-9]+$")

MAX_DESCRIPTION_CHARS = 300

#: Types that must carry an explicit charset even though they are not ``text/*``
#: (docs/06 §6). The loader appends ``; charset=utf-8`` when the catalog omits it.
CHARSET_BEARING_APPLICATION_TYPES = frozenset(
    {
        "application/json",
        "application/xml",
        "application/yaml",
        "application/toml",
        "application/x-ndjson",
        "application/geo+json",
    }
)


class Family(StrEnum):
    DOCUMENTS = "documents"
    IMAGES = "images"
    VIDEO = "video"
    AUDIO = "audio"
    DATA = "data"
    TEXT = "text"
    WEB = "web"
    ARCHIVES = "archives"
    FONTS = "fonts"
    BINARY = "binary"
    CALENDAR_MAIL = "calendar-mail"
    CERTIFICATES = "certificates"
    EDGE = "edge"


class SizeClass(StrEnum):
    EXACT = "exact"
    BOUNDARY = "boundary"
    APPROX = "approx"
    FREE = "free"


class Status(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class Defect(StrEnum):
    """Closed enum from docs/04 §1.3. It tells the validator what to assert."""

    ZERO_BYTE = "zero-byte"
    TRUNCATED = "truncated"
    MISMATCHED_EXTENSION = "mismatched-extension"
    MAGIC_PREFIX = "magic-prefix"
    INVALID_SYNTAX = "invalid-syntax"
    INVALID_ENCODING = "invalid-encoding"
    NONSTANDARD = "nonstandard"
    BOM = "bom"
    STRESS = "stress"
    HOSTILE_NAME = "hostile-name"


class Outcome(StrEnum):
    """What a broken file does to a reader, as a property of the file (docs/04 §1.3.1).

    Declared per fixture and **derived independently** by the edge validator from two
    readings of the bytes; the two must agree or the fixture fails. The derivation is
    the definition: whether any conforming reader gets the whole content, part of it,
    or nothing.
    """

    #: Nothing conforming reads anything out of it. A reader that succeeds is wrong.
    MUST_FAIL = "must-fail"
    #: Part of the content survives and a conforming reader may return it.
    MAY_RECOVER = "may-recover"
    #: Some conforming reader takes the file whole while another refuses it.
    VARIES = "varies"


SIZE_CLASSES_NEEDING_NOMINAL = {SizeClass.EXACT, SizeClass.BOUNDARY, SizeClass.APPROX}


class CatalogError(ValueError):
    """Raised when the catalog is internally inconsistent across files."""


class Removed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    removed_at: str = Field(min_length=1)  # RFC 3339


class Edge(BaseModel):
    """The ``edge`` block, required for every fixture under ``edge/``."""

    model_config = ConfigDict(extra="forbid")

    intended_format: str = Field(pattern=FORMAT_RE.pattern)
    defect: Defect
    #: The valid fixture of the same type to test a reader against, so that "it
    #: refused" can be told apart from "it refuses everything". Cross-checked in
    #: :meth:`Catalog._check_edge_comparisons`.
    compare_with: str = Field(min_length=1)
    #: What the file does to a reader. The validator derives it again from the bytes
    #: and fails the fixture if the two disagree.
    outcome: Outcome
    source_fixture: str | None = None
    fraction: float | None = Field(default=None, gt=0, lt=1)
    magic: str | None = None

    @model_validator(mode="after")
    def _defect_specific_fields(self) -> Self:
        if self.defect is Defect.TRUNCATED and self.fraction is None:
            raise ValueError("edge.fraction is required when defect is 'truncated'")
        if self.defect is Defect.MAGIC_PREFIX and not self.magic:
            raise ValueError("edge.magic is required when defect is 'magic-prefix'")
        if self.fraction is not None and self.defect is not Defect.TRUNCATED:
            raise ValueError("edge.fraction is only meaningful for defect 'truncated'")
        if self.magic is not None and self.defect is not Defect.MAGIC_PREFIX:
            raise ValueError("edge.magic is only meaningful for defect 'magic-prefix'")
        return self


class Fixture(BaseModel):
    """One row of ``catalog/{format}.yaml``. Field rules are docs/06 §3."""

    model_config = ConfigDict(extra="forbid")

    name: str
    phase: Annotated[int, Field(ge=1, le=4)]
    generator: str = Field(pattern=r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)
    tags: list[str] = Field(min_length=1)
    expect: dict[str, Any] | None = None
    size_class: SizeClass
    nominal_bytes: int | None = Field(default=None, gt=0)
    mime: str | None = None
    edge_case: bool = False
    depends_on: list[str] = Field(default_factory=list)
    allow_large: bool = False
    status: Status = Status.ACTIVE
    removed: Removed | None = None
    notes: str | None = None
    #: Why this fixture is known not to reproduce byte for byte off the reference fleet
    #: (docs/06 §4). Set only for paths whose encoder dispatches on CPU features. The
    #: monthly audit reports these separately from real drift, because an alert that
    #: fires on expected behaviour every quarter is how alerting dies. A typed field
    #: rather than a marker inside `notes`: the audit has to classify on it, and prose
    #: that has to be parsed goes wrong the first time someone rewords it.
    expected_drift: str | None = Field(default=None, min_length=1)
    #: Catalogued, deliberately **not** in the manifest yet, and why. An
    #: `expected_drift` fixture may only enter the manifest in a run that also publishes
    #: its bytes, because those bytes cannot be rebuilt afterwards (docs/06 §4). Until
    #: the uploader exists the row stays here and the manifest stays silent — an entry
    #: describing bytes that exist nowhere is worse than no entry at all.
    awaiting_publication: str | None = Field(default=None, min_length=1)
    policy_exceptions: list[str] = Field(default_factory=list)
    edge: Edge | None = None

    # The owning format, injected by the loader so a Fixture can compute its own path.
    format: str = Field(pattern=FORMAT_RE.pattern)

    @model_validator(mode="after")
    def _check(self) -> Self:
        self._check_name()
        if self.expect is None and not self.edge_case:
            raise ValueError("expect is required unless edge_case is true")
        if self.size_class in SIZE_CLASSES_NEEDING_NOMINAL and self.nominal_bytes is None:
            raise ValueError(f"nominal_bytes is required for size_class '{self.size_class}'")
        if self.size_class is SizeClass.FREE and self.nominal_bytes is not None:
            raise ValueError("nominal_bytes is meaningless for size_class 'free'")
        if self.format == "edge" and self.edge is None:
            raise ValueError("every fixture under edge/ needs an 'edge' block")
        if self.format != "edge" and self.edge is not None:
            raise ValueError("only fixtures under edge/ may carry an 'edge' block")
        if self.format == "edge" and not self.edge_case:
            raise ValueError("fixtures under edge/ must set edge_case: true")
        if self.status is Status.REMOVED and self.removed is None:
            raise ValueError("removed is required when status is 'removed'")
        if self.status is Status.ACTIVE and self.removed is not None:
            raise ValueError("removed is only allowed when status is 'removed'")
        return self

    def _check_name(self) -> None:
        pattern = HLS_NAME_RE if self.format == "hls" else NAME_RE
        if not pattern.match(self.name):
            hint = (
                "hls names are '{variant}/index.m3u8', '{variant}/master.m3u8' "
                "or '{variant}/seg-NNN.ts'"
                if self.format == "hls"
                else "lowercase kebab-case followed by one or more extensions"
            )
            raise ValueError(f"name '{self.name}' does not match the grammar: {hint}")

    @property
    def path(self) -> str:
        return f"{self.format}/{self.name}"

    @property
    def ext(self) -> str:
        """Everything after the first dot of the last path segment.

        ``3-text-files.tar.gz`` → ``tar.gz``; ``hls/720p-10s/index.m3u8`` → ``m3u8``.
        """
        last = self.path.rsplit("/", 1)[-1]
        return last.split(".", 1)[1]


class FormatCatalog(BaseModel):
    """One ``catalog/{format}.yaml`` file."""

    model_config = ConfigDict(extra="forbid")

    format: str = Field(pattern=FORMAT_RE.pattern)
    family: Family
    mime: str = Field(min_length=1)
    description: str = Field(min_length=1)
    seo_title: str = Field(min_length=1)
    related: list[str] = Field(default_factory=list)
    fixtures: list[Fixture] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_names(self) -> Self:
        seen: set[str] = set()
        for fixture in self.fixtures:
            if fixture.name in seen:
                raise ValueError(f"duplicate fixture name '{fixture.name}'")
            seen.add(fixture.name)
        return self

    def mime_for(self, fixture: Fixture) -> str:
        """The exact ``Content-Type`` served for a fixture.

        The per-fixture override wins. Otherwise the format default is used, and
        ``; charset=utf-8`` is appended when the type is text-like and carries no
        charset already (docs/05 §1 rule 7, docs/06 §6 "text hygiene"). Anything not in
        that set — ``application/xhtml+xml`` among them — states its charset explicitly
        in the catalog rather than relying on a rule that would have to guess.
        """
        mime = fixture.mime or self.mime
        base = mime.split(";", 1)[0].strip()
        text_like = base.startswith("text/") or base in CHARSET_BEARING_APPLICATION_TYPES
        if text_like and "charset=" not in mime:
            mime = f"{mime}; charset=utf-8"
        return mime


class Catalog:
    """Every ``catalog/*.yaml`` loaded together, with cross-file checks."""

    def __init__(self, formats: list[FormatCatalog], tags: list[str]) -> None:
        self.formats = sorted(formats, key=lambda f: f.format)
        self.tags = tags
        self._validate()

    # -- loading ------------------------------------------------------------

    @classmethod
    def load(cls, directory: Path | None = None) -> Catalog:
        directory = directory or config.catalog_dir()
        tags = cls._load_tags(directory / "_tags.yaml")
        formats = [
            cls._load_format(path)
            for path in sorted(directory.glob("*.yaml"))
            if not path.name.startswith("_")
        ]
        return cls(formats, tags)

    @staticmethod
    def _load_tags(path: Path) -> list[str]:
        if not path.is_file():
            raise CatalogError(f"missing tag vocabulary: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tags = data.get("tags")
        if not isinstance(tags, list) or not tags:
            raise CatalogError(f"{path} must contain a non-empty 'tags' list")
        if len(tags) != len(set(tags)):
            raise CatalogError(f"{path} contains duplicate tags")
        return list(tags)

    @staticmethod
    def _load_format(path: Path) -> FormatCatalog:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise CatalogError(f"{path} must contain a mapping")
        fmt = data.get("format")
        for fixture in data.get("fixtures") or []:
            if isinstance(fixture, dict):
                fixture.setdefault("format", fmt)
        catalog = FormatCatalog.model_validate(data)
        if catalog.format != path.stem:
            raise CatalogError(f"{path} declares format '{catalog.format}'")
        return catalog

    # -- cross-file validation ---------------------------------------------

    def _validate(self) -> None:
        self._check_unique_paths()
        self._check_tags()
        self._check_related()
        self._check_dependencies()
        self._check_edge_comparisons()

    def _check_unique_paths(self) -> None:
        seen: set[str] = set()
        for fixture in self.fixtures():
            if fixture.path in seen:
                raise CatalogError(f"duplicate fixture path '{fixture.path}'")
            seen.add(fixture.path)

    def _check_tags(self) -> None:
        allowed = set(self.tags)
        for fixture in self.fixtures():
            unknown = sorted(set(fixture.tags) - allowed)
            if unknown:
                raise CatalogError(
                    f"{fixture.path}: tags not in catalog/_tags.yaml: {', '.join(unknown)}"
                )

    def _check_related(self) -> None:
        known = {f.format for f in self.formats}
        for fmt in self.formats:
            unknown = sorted(set(fmt.related) - known)
            if unknown:
                joined = ", ".join(unknown)
                raise CatalogError(
                    f"catalog/{fmt.format}.yaml: related names unknown formats: {joined}"
                )
            if fmt.format in fmt.related:
                raise CatalogError(f"catalog/{fmt.format}.yaml: related lists itself")

    def _check_dependencies(self) -> None:
        by_path = self.by_path
        for fixture in self.fixtures():
            for dependency in fixture.depends_on:
                target = by_path.get(dependency)
                if target is None:
                    raise CatalogError(f"{fixture.path}: depends_on unknown path '{dependency}'")
                # A phase-1 fixture cannot be built from something published later.
                if target.phase > fixture.phase:
                    raise CatalogError(
                        f"{fixture.path} (phase {fixture.phase}) depends on "
                        f"{target.path} (phase {target.phase})"
                    )
        self._check_acyclic()

    def _check_edge_comparisons(self) -> None:
        """``edge.compare_with`` must name a valid, published fixture of the same type.

        "Valid" needs no separate proof: an active fixture only reaches the manifest
        once its own validator has measured it (`manifest update`), so naming one is
        naming something that passed. What is checked here is that the comparison is
        the right one — same announced type, not another broken file, and the twin
        itself when the edge case was cut from a file of that type.
        """
        by_path = self.by_path
        for fixture in self.fixtures():
            if fixture.edge is None:
                continue
            target = by_path.get(fixture.edge.compare_with)
            if target is None:
                raise CatalogError(
                    f"{fixture.path}: compare_with unknown path '{fixture.edge.compare_with}'"
                )
            if target.format != fixture.ext:
                raise CatalogError(
                    f"{fixture.path}: compare_with is {target.path} (format {target.format}), "
                    f"but this one announces itself as {fixture.ext}"
                )
            if target.edge_case or target.status is not Status.ACTIVE:
                raise CatalogError(
                    f"{fixture.path}: compare_with must name a valid, active fixture, "
                    f"and {target.path} is not one"
                )
            if target.phase > fixture.phase:
                raise CatalogError(
                    f"{fixture.path} (phase {fixture.phase}) compares with "
                    f"{target.path} (phase {target.phase})"
                )
            source = fixture.edge.source_fixture
            if source is not None and source not in by_path:
                raise CatalogError(f"{fixture.path}: source_fixture unknown path '{source}'")
            same_type_source = source is not None and by_path[source].format == fixture.ext
            if same_type_source and source != fixture.edge.compare_with:
                raise CatalogError(
                    f"{fixture.path}: it was cut from {source}, which is the file to "
                    f"compare with, not {target.path}"
                )

    def _check_acyclic(self) -> None:
        by_path = self.by_path
        temporary: set[str] = set()
        done: set[str] = set()

        def visit(path: str, trail: list[str]) -> None:
            if path in done:
                return
            if path in temporary:
                cycle = " -> ".join([*trail, path])
                raise CatalogError(f"depends_on cycle: {cycle}")
            temporary.add(path)
            for dependency in by_path[path].depends_on:
                visit(dependency, [*trail, path])
            temporary.discard(path)
            done.add(path)

        for path in by_path:
            visit(path, [])

    # -- access -------------------------------------------------------------

    def fixtures(self) -> Iterator[Fixture]:
        for fmt in self.formats:
            yield from fmt.fixtures

    @cached_property
    def by_path(self) -> dict[str, Fixture]:
        return {fixture.path: fixture for fixture in self.fixtures()}

    @cached_property
    def format_by_name(self) -> dict[str, FormatCatalog]:
        return {fmt.format: fmt for fmt in self.formats}

    def mime_for(self, fixture: Fixture) -> str:
        return self.format_by_name[fixture.format].mime_for(fixture)
