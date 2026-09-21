"""Raw byte fixtures — ``bin/`` (docs/05 §3.10).

The simplest family, and the one people reach for most: upload limits, byte-range
requests, checksum plumbing. Every pattern is a pure function of the fixture's seed or a
constant, so there is nothing to go wrong and nothing to drift.
"""

from __future__ import annotations

from loremfile.generators.base import GeneratorContext, generator

#: The repeating ramp used by ``incrementing-*.bin``.
RAMP = bytes(range(256))


@generator()
def shake(ctx: GeneratorContext, *, size: int) -> bytes:
    """``size`` pseudo-random bytes from SHAKE-256 seeded with the fixture's path.

    High entropy, so it does not compress — which is what makes it honest for testing
    an upload limit or a transfer rate.
    """
    return ctx.stream(size)


@generator()
def zeros(_ctx: GeneratorContext, *, size: int) -> bytes:
    """``size`` NUL bytes. Compresses to almost nothing, which is the point."""
    return b"\x00" * size


@generator()
def ones(_ctx: GeneratorContext, *, size: int) -> bytes:
    """``size`` 0xFF bytes."""
    return b"\xff" * size


@generator()
def incrementing(_ctx: GeneratorContext, *, size: int) -> bytes:
    """``0x00``…``0xFF`` repeating, truncated to ``size``.

    Every byte value appears, and the offset of any byte is obvious by eye — useful when
    checking that a range request returned the range it claimed.
    """
    repeats = size // len(RAMP) + 1
    return (RAMP * repeats)[:size]
