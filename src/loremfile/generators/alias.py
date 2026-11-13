"""Aliases: a new permanent path that serves the bytes of an existing one (docs/05 §8).

An alias is never built from its own recipe. It reads the original through `ctx.dependency`, so
it is the bytes that were published and not a rebuild that might differ, and the test that holds
the two to equal SHA-256 has nothing to explain.
"""

from __future__ import annotations

from loremfile.generators.base import GeneratorContext, generator


@generator()
def copy(ctx: GeneratorContext, *, of: str) -> bytes:
    """The bytes of `of`, unchanged."""
    return ctx.dependency(of)
