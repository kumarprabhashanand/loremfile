"""Validator for ``bin/`` fixtures (docs/04 §1.3: props = ``pattern``)."""

from __future__ import annotations

import hashlib
from typing import Any

from loremfile.catalog import Fixture
from loremfile.validators import ValidationError, register

RAMP = bytes(range(256))


def _detect_pattern(data: bytes) -> str:
    """Name the pattern from the bytes themselves, rather than trusting the catalog."""
    if not data:
        return "empty"
    if data == b"\x00" * len(data):
        return "zeros"
    if data == b"\xff" * len(data):
        return "ones"
    repeats = len(data) // len(RAMP) + 1
    if data == (RAMP * repeats)[: len(data)]:
        return "incrementing"
    return "shake256"


@register("bin")
def validate_bin(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    """Measure the pattern, and prove a shake256 fixture really is its own seed's stream.

    Regenerating the stream here is the independent check: it catches a generator that
    silently stopped using ``ctx.seed`` — which would still look like random bytes.
    """
    pattern = _detect_pattern(data)
    if pattern == "shake256":
        expected = hashlib.shake_256(
            hashlib.sha256(f"loremfile:{fixture.path}".encode()).digest()
        ).digest(len(data))
        if data != expected:
            raise ValidationError("bytes are not the SHAKE-256 stream of this fixture's own seed")
    return {"pattern": pattern}
