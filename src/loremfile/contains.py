"""What a generator fed into a fixture, for checking `contains_text` (docs/04 §1.3.2).

A `contains_text` string must come from the generator's own input, never from what a
reader extracted. This runs the generator once more and records that input: every lorem
string it drew, every dataset value it read, and the literals in its module. The bytes
come back too, so a caller can confirm it recorded the published file and not another.
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loremfile.catalog import Fixture
from loremfile.datasets import cached_rows
from loremfile.generators.base import REGISTRY, DependencyResolver, GeneratorContext
from loremfile.util import lorem
from loremfile.util.determinism import deterministic

#: The lorem functions a generator draws text through.
DRAWS = ("words", "sentence", "paragraph", "text", "pseudo_text", "emoji_run")


@dataclass
class Recorded:
    data: bytes
    #: Every lorem string drawn and every dataset value read, as the generator wrote it.
    drawn: list[str] = field(default_factory=list)
    #: The generator's module: the literal text it writes is in here.
    source: str = ""

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def supplies(self, string: str) -> bool:
        """Did the generator's input hold this string, whole?"""
        return string in self.source or any(string in unit for unit in self.drawn)


@contextlib.contextmanager
def _recording_lorem(drawn: list[str]) -> Iterator[None]:
    originals = {name: getattr(lorem, name) for name in DRAWS}

    def wrap(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
        def recorded(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - passes through
            value = function(*args, **kwargs)
            drawn.append(" ".join(value) if name == "words" else str(value))
            return value

        return recorded

    for name, function in originals.items():
        setattr(lorem, name, wrap(name, function))
    try:
        yield
    finally:
        for name, function in originals.items():
            setattr(lorem, name, function)


def record(fixture: Fixture, workdir: Path, resolver: DependencyResolver | None = None) -> Recorded:
    """Generate ``fixture`` exactly as the build does, recording its input."""
    generator = REGISTRY.get(fixture.generator)
    drawn: list[str] = []

    def dataset(name: str, count: int) -> list[dict[str, Any]]:
        rows = cached_rows(name, count)  # type: ignore[arg-type]
        drawn.extend(str(value) for row in rows for value in row.values())
        return rows

    context = GeneratorContext(path=fixture.path, workdir=workdir, _dataset=dataset)
    if resolver is not None:
        context._dependency = resolver
    with _recording_lorem(drawn), deterministic(context.seed):
        result = generator(context, **fixture.params)
    data = result.read_bytes() if isinstance(result, Path) else result
    module = inspect.getmodule(generator.func)
    return Recorded(data=data, drawn=drawn, source=inspect.getsource(module) if module else "")
