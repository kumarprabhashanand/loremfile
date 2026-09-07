"""M1.7: the generator contract — context, decorator, registry (docs/06 §4)."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from loremfile.config import SOURCE_DATE_EPOCH
from loremfile.generators.base import (
    Generator,
    GeneratorContext,
    GeneratorRegistry,
)
from loremfile.util.determinism import seed_for

WORKDIR = Path(tempfile.gettempdir())


def ctx(path: str = "pdf/a4-3pages.pdf", tmp: Path | None = None) -> GeneratorContext:
    return GeneratorContext(path=path, workdir=tmp or WORKDIR)


def test_seed_comes_from_the_full_path() -> None:
    assert ctx().seed == seed_for("pdf/a4-3pages.pdf")
    assert ctx("bin/1mb.bin").seed != ctx("bin/2mb.bin").seed


def test_epoch_is_the_fixed_build_clock() -> None:
    assert ctx().epoch == SOURCE_DATE_EPOCH


def test_rng_restarts_each_time_it_is_read() -> None:
    """A generator that asks twice must get the same stream both times, so an
    order-dependent generator fails its determinism test loudly."""
    context = ctx()
    assert context.rng.random() == context.rng.random()


def test_rng_differs_between_fixtures() -> None:
    assert ctx("a/b.bin").rng.random() != ctx("c/d.bin").rng.random()


def test_stream_is_reproducible_and_sized() -> None:
    context = ctx()
    assert context.stream(64) == context.stream(64)
    assert len(context.stream(1000)) == 1000


def test_stream_differs_between_fixtures() -> None:
    assert ctx("a/b.bin").stream(32) != ctx("c/d.bin").stream(32)


def test_dataset_is_reachable_through_the_context() -> None:
    rows = ctx().dataset("people", 3)
    assert [row["id"] for row in rows] == [1, 2, 3]


def test_dependency_without_a_resolver_fails_clearly() -> None:
    with pytest.raises(RuntimeError, match="cannot resolve dependencies"):
        ctx().dependency("pdf/other.pdf")


def test_dependency_uses_the_injected_resolver() -> None:
    context = GeneratorContext(
        path="edge/truncated.pdf",
        workdir=WORKDIR,
        _dependency=lambda path: f"bytes of {path}".encode(),
    )
    assert context.dependency("pdf/a4-3pages.pdf") == b"bytes of pdf/a4-3pages.pdf"


def test_tool_lookup_reports_a_missing_binary_usefully() -> None:
    with pytest.raises(Exception, match="not on PATH"):
        ctx().tool("definitely-not-a-real-binary")


# --- the registry ----------------------------------------------------------


def make(name: str, *, parallel_safe: bool = True) -> Generator:
    return Generator(name=name, func=lambda _ctx, **_kw: b"", parallel_safe=parallel_safe)


def test_registry_round_trip() -> None:
    registry = GeneratorRegistry()
    registry.register(make("pdf.basic"))
    assert "pdf.basic" in registry
    assert registry.get("pdf.basic").name == "pdf.basic"
    assert len(registry) == 1


def test_registry_rejects_a_duplicate_name() -> None:
    registry = GeneratorRegistry()
    registry.register(make("pdf.basic"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(make("pdf.basic"))


def test_registry_error_explains_the_naming_convention() -> None:
    with pytest.raises(KeyError, match=re.escape("<module>.<function>")):
        GeneratorRegistry().get("pdf.missing")


def test_registry_iterates_in_sorted_order() -> None:
    registry = GeneratorRegistry()
    for name in ("png.solid", "pdf.basic", "bin.pattern"):
        registry.register(make(name))
    assert list(registry) == ["bin.pattern", "pdf.basic", "png.solid"]


def test_parallel_safe_is_carried_through() -> None:
    registry = GeneratorRegistry()
    registry.register(make("image.huge", parallel_safe=False))
    assert registry.get("image.huge").parallel_safe is False


def test_generator_is_callable_with_params() -> None:
    captured: dict[str, object] = {}

    def func(_context: GeneratorContext, **params: object) -> bytes:
        captured.update(params)
        return b"out"

    generator = Generator(name="x.y", func=func, parallel_safe=True)
    assert generator(ctx(), pages=3, page_size="A4") == b"out"
    assert captured == {"pages": 3, "page_size": "A4"}
