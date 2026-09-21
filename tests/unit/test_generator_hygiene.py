"""Generators must draw from ctx, not from ambient randomness or the clock.

docs/06 §4 promises this test exists: ``util/determinism`` patches those sources so
third-party libraries keep working, but our own generator code has no excuse — it is
handed ``ctx.rng``, ``ctx.stream`` and ``ctx.epoch``. A generator reading the real clock
would produce different bytes on every build and break the immutability guarantee.

The check parses each module's **AST** rather than grepping its text. Text matching
fired on a docstring in ``generators/pdf.py`` that merely *mentions* ``os.urandom`` while
explaining why the determinism guard covers it — a false positive that would have
pressured the next author to write worse documentation to appease the test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

GENERATORS = Path(__file__).resolve().parents[2] / "src" / "loremfile" / "generators"

#: (module, attribute) pairs a generator must not call, with what to use instead.
FORBIDDEN: tuple[tuple[str, str, str], ...] = (
    ("random", "random", "use ctx.rng"),
    ("random", "randint", "use ctx.rng"),
    ("random", "choice", "use ctx.rng"),
    ("random", "randrange", "use ctx.rng"),
    ("random", "shuffle", "use ctx.rng"),
    ("random", "sample", "use ctx.rng"),
    ("random", "uniform", "use ctx.rng"),
    ("random", "getrandbits", "use ctx.rng"),
    ("os", "urandom", "use ctx.stream or ctx.rng"),
    ("secrets", "token_bytes", "use ctx.stream"),
    ("uuid", "uuid4", "derive identifiers from ctx.seed"),
    ("time", "time", "use ctx.epoch"),
    ("time", "time_ns", "use ctx.epoch"),
    ("datetime", "now", "use ctx.epoch"),
    ("datetime", "utcnow", "use ctx.epoch"),
    ("dt", "now", "use ctx.epoch"),
    ("dt", "utcnow", "use ctx.epoch"),
)

#: base.py builds the context itself, so it is the one module allowed to touch these.
EXEMPT = {"base.py"}


def generator_modules() -> list[Path]:
    return sorted(p for p in GENERATORS.glob("*.py") if p.name not in EXEMPT)


def offending_calls(source: str) -> list[tuple[int, str]]:
    """Every ``module.attribute`` access in the file that names a forbidden source."""
    tree = ast.parse(source)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        owner = node.value
        # Only bare `name.attr`; `self.rng.random()` and `ctx.rng.choice()` are fine.
        if not isinstance(owner, ast.Name):
            continue
        for module, attribute, advice in FORBIDDEN:
            if owner.id == module and node.attr == attribute:
                hits.append((node.lineno, f"{module}.{attribute} ({advice})"))
    return hits


def test_the_generators_package_exists() -> None:
    assert generator_modules(), "no generator modules found"


@pytest.mark.parametrize("module", generator_modules(), ids=lambda p: p.name)
def test_no_generator_uses_ambient_nondeterminism(module: Path) -> None:
    hits = offending_calls(module.read_text(encoding="utf-8"))
    assert not hits, "\n  ".join(
        [f"{module.name} must draw from ctx:", *(f"line {n}: {w}" for n, w in hits)]
    )


def test_the_check_fires_on_a_real_call() -> None:
    """A guard that cannot fail is not a guard."""
    hits = offending_calls("import os\nx = os.urandom(8)\n")
    assert hits and "os.urandom" in hits[0][1]


def test_the_check_ignores_prose_that_merely_names_a_forbidden_source() -> None:
    """The false positive that motivated moving from grep to AST."""
    source = '"""fpdf2 draws its IV from os.urandom, which the guard patches."""\n'
    assert offending_calls(source) == []


def test_the_check_ignores_a_seeded_rng_on_the_context() -> None:
    assert offending_calls("y = ctx.rng.random()\nz = ctx.rng.choice([1])\n") == []
