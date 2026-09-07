"""Generators must draw from ctx, not from ambient randomness or the clock.

docs/06 §4 promises this test exists: ``util/determinism`` patches those sources so
third-party libraries keep working, but our own generator code has no excuse — it is
handed ``ctx.rng`` and ``ctx.epoch``. A generator reading the real clock would produce
different bytes on every build and break the immutability guarantee.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

GENERATORS = Path(__file__).resolve().parents[2] / "src" / "loremfile" / "generators"

#: Patterns that mean "this module is making its own nondeterminism".
FORBIDDEN = (
    (re.compile(r"\brandom\.(?!Random\b)"), "use ctx.rng, not the random module"),
    (re.compile(r"\bdatetime\.now\b"), "use ctx.epoch, not the wall clock"),
    (re.compile(r"\bdatetime\.utcnow\b"), "use ctx.epoch, not the wall clock"),
    (re.compile(r"\btime\.time\b"), "use ctx.epoch, not the wall clock"),
    (re.compile(r"\bos\.urandom\b"), "use ctx.stream or ctx.rng"),
    (re.compile(r"\buuid\.uuid4\b"), "derive identifiers from ctx.seed"),
    (re.compile(r"\bos\.environ\b"), "generators read nothing but ctx"),
)

#: base.py is the one module allowed to touch these: it builds the context itself.
EXEMPT = {"base.py"}


def generator_modules() -> list[Path]:
    return sorted(p for p in GENERATORS.glob("*.py") if p.name not in EXEMPT)


def test_the_generators_package_exists() -> None:
    assert GENERATORS.is_dir()


@pytest.mark.parametrize("pattern_and_reason", FORBIDDEN, ids=lambda pr: pr[0].pattern)
def test_no_generator_uses_ambient_nondeterminism(
    pattern_and_reason: tuple[re.Pattern[str], str],
) -> None:
    pattern, reason = pattern_and_reason
    hits: list[str] = []
    for module in generator_modules():
        for number, line in enumerate(module.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if pattern.search(code):
                hits.append(f"{module.name}:{number}: {line.strip()}  ({reason})")
    assert not hits, "\n  ".join(["generators must be deterministic:", *hits])


def test_the_check_would_actually_fire(tmp_path: Path) -> None:
    """A guard that cannot fail is not a guard."""
    offender = tmp_path / "bad.py"
    offender.write_text("import random\nx = random.random()\n", encoding="utf-8")
    pattern = FORBIDDEN[0][0]
    assert any(pattern.search(line) for line in offender.read_text().splitlines())
