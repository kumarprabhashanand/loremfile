"""The generator contract: context, decorator and registry (docs/06 §4).

A generator is a pure function of ``(ctx, params)``. It receives everything it may read
through ``ctx`` — the seed, an RNG, the shared datasets, its dependencies, tool paths and
the fixed epoch — and returns either ``bytes`` or a ``Path`` inside ``ctx.workdir``.

It must not read the wall clock, the environment, the network or the locale.
``util.determinism`` patches those for third-party libraries that do it anyway; a unit
test greps this package for ``random.`` and ``datetime.now`` so our own code cannot.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypeVar

from loremfile import datasets
from loremfile.config import SOURCE_DATE_EPOCH
from loremfile.util.determinism import seed_for
from loremfile.util.ffmpeg import tool as _tool

#: A generator returns raw bytes, or a path to a file it wrote in ``ctx.workdir``.
GeneratorResult = bytes | Path

#: Bound to the decorated function so `@generator()` preserves its exact signature.
#: Without this every generator would appear to return `bytes | Path` to callers, and a
#: generator calling another one would have to re-narrow the type for no reason.
GeneratorFunc = TypeVar("GeneratorFunc", bound=Callable[..., GeneratorResult])


class DependencyResolver(Protocol):
    """How a context fetches a fixture this one is built from.

    The build supplies the real implementation (docs/06 §4): use ``build/fixtures`` if
    the fixture was made in this run, otherwise download the **published** bytes and
    check them against the manifest, otherwise generate it first. It never regenerates
    something already published — that is what keeps a derived fixture stable when its
    source's generator changes.
    """

    def __call__(self, path: str) -> bytes: ...


class DatasetProvider(Protocol):
    def __call__(self, name: str, count: int) -> list[dict[str, Any]]: ...


def _default_dependency(path: str) -> bytes:
    raise RuntimeError(
        f"this context cannot resolve dependencies, so '{path}' is unavailable; "
        "the build supplies a resolver (docs/06 §4)"
    )


def _default_dataset(name: str, count: int) -> list[dict[str, Any]]:
    return datasets.cached_rows(name, count)  # type: ignore[arg-type]


@dataclass
class GeneratorContext:
    """Everything a generator is allowed to read."""

    path: str
    workdir: Path
    epoch: int = SOURCE_DATE_EPOCH
    _dependency: DependencyResolver = field(default=_default_dependency, repr=False)
    _dataset: DatasetProvider = field(default=_default_dataset, repr=False)

    @property
    def seed(self) -> bytes:
        """``sha256("loremfile:" + path)``. Two fixtures never share a stream."""
        return seed_for(self.path)

    @property
    def rng(self) -> random.Random:
        """A fresh RNG seeded from :attr:`seed`.

        A property rather than a stored attribute so a generator that asks twice starts
        from the same place both times, which makes a generator that is accidentally
        order-dependent fail its determinism test loudly rather than subtly.
        """
        return random.Random(self.seed)  # noqa: S311 - reproducibility, not crypto

    def dataset(self, name: str, count: int) -> list[dict[str, Any]]:
        """Rows from a shared dataset (docs/05 §2). Smaller counts are prefixes."""
        return self._dataset(name, count)

    def dependency(self, path: str) -> bytes:
        """The bytes of another fixture. Never regenerates a published one."""
        return self._dependency(path)

    def tool(self, name: str) -> str:
        """Absolute path to a toolchain binary."""
        return _tool(name)

    def stream(self, size: int) -> bytes:
        """``size`` reproducible bytes derived from this fixture's seed.

        SHAKE-256, so a 100 MB binary fixture costs one call and no state juggling.
        """
        return hashlib.shake_256(self.seed).digest(size)


@dataclass(frozen=True)
class Generator:
    """A registered generator function and the properties the build needs."""

    name: str
    func: Callable[..., GeneratorResult]
    parallel_safe: bool

    def __call__(self, ctx: GeneratorContext, **params: object) -> GeneratorResult:
        return self.func(ctx, **params)


class GeneratorRegistry:
    """``module.function`` → generator, matching the catalog's ``generator`` field."""

    def __init__(self) -> None:
        self._entries: dict[str, Generator] = {}

    def register(self, generator: Generator) -> None:
        if generator.name in self._entries:
            raise ValueError(f"generator '{generator.name}' is already registered")
        self._entries[generator.name] = generator

    def get(self, name: str) -> Generator:
        try:
            return self._entries[name]
        except KeyError:
            raise KeyError(
                f"no generator named '{name}'. Catalog entries name their generator as "
                "'<module>.<function>', and the module must be imported."
            ) from None

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._entries))

    def __len__(self) -> int:
        return len(self._entries)


#: The process-wide registry the build reads.
REGISTRY = GeneratorRegistry()


def generator(*, parallel_safe: bool = True) -> Callable[[GeneratorFunc], GeneratorFunc]:
    """Register a generator.

    ``parallel_safe=False`` for the memory-heavy ones — an 8000x8000 PNG, a 100k-row
    dataset — which the build runs on their own rather than alongside others.

    The registered name is ``<module>.<function>``, using the module's last path
    component, so ``loremfile.generators.pdf.basic`` registers as ``pdf.basic`` and
    matches the catalog verbatim.
    """

    def decorate(func: GeneratorFunc) -> GeneratorFunc:
        module = func.__module__.rsplit(".", 1)[-1]
        REGISTRY.register(
            Generator(name=f"{module}.{func.__name__}", func=func, parallel_safe=parallel_safe)
        )
        return func

    return decorate
