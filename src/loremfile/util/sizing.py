"""Hitting a target byte size, and checking the size classes (docs/05 §4 and §6).

Some fixtures promise a size in their name. ``bin/10mb.bin`` must be exactly
10,000,000 bytes; ``pdf/1mb.pdf`` must be within 5 %. For formats where size is not a
direct function of the content — a PDF, a zip, an MP3 — ``fit`` searches for the one
monotone parameter that lands inside the tolerance.

A fixture is never published outside its size class: if ``fit`` cannot converge it
raises, and the build fails.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from loremfile.config import APPROX_TOLERANCE

#: Decimal units, as used in fixture names: 1 MB = 1,000,000 bytes.
DECIMAL_UNITS = {"b": 1, "kb": 10**3, "mb": 10**6, "gb": 10**9}
#: Binary units: 1 MiB = 1,048,576 bytes.
BINARY_UNITS = {"kib": 2**10, "mib": 2**20, "gib": 2**30}
UNITS = {**DECIMAL_UNITS, **BINARY_UNITS}

#: ``10mb``, ``10mib``, ``10mib-plus-1``, ``10mb-minus-1``.
SIZE_TOKEN = re.compile(
    r"^(?P<count>\d+)(?P<unit>b|kb|mb|gb|kib|mib|gib)"
    r"(?:-(?P<direction>plus|minus)-(?P<delta>\d+))?$"
)


class SizingError(RuntimeError):
    """A size target could not be met. Always fatal: never publish a wrong size."""


def parse_size_token(token: str) -> int | None:
    """Bytes described by a size token, or ``None`` if it is not one.

    ``10mb`` → 10,000,000; ``10mib`` → 10,485,760; ``10mib-plus-1`` → 10,485,761.
    """
    match = SIZE_TOKEN.match(token)
    if not match:
        return None
    total = int(match["count"]) * UNITS[match["unit"]]
    if match["direction"] == "plus":
        total += int(match["delta"])
    elif match["direction"] == "minus":
        total -= int(match["delta"])
    return total


def size_matches(actual: int, size_class: str, nominal: int | None) -> bool:
    """Does ``actual`` satisfy the class the catalog claims? (docs/06 §6 step 4)"""
    if size_class == "free":
        return True
    if nominal is None:
        raise SizingError(f"size_class '{size_class}' needs nominal_bytes")
    if size_class == "exact":
        return actual == nominal
    if size_class == "boundary":
        return abs(actual - nominal) == 1
    if size_class == "approx":
        return abs(actual - nominal) <= APPROX_TOLERANCE * nominal
    raise SizingError(f"unknown size_class '{size_class}'")


def pad_to(
    payload: bytes, target: int, *, filler: bytes = b" ", terminator: bytes = b"\n"
) -> bytes:
    """Pad to exactly ``target`` bytes, keeping a trailing newline (docs/05 §6).

    Text fixtures with an exact size are cut at a word or line boundary, then padded
    with spaces to ``target - 1`` and ended with a newline, so the file still reads as
    text rather than ending mid-word.
    """
    if len(terminator) > target:
        raise SizingError(f"target {target} is smaller than the terminator")
    body = payload[: target - len(terminator)]
    padding = target - len(terminator) - len(body)
    if padding % len(filler):
        raise SizingError("padding is not a whole number of filler units")
    return body + filler * (padding // len(filler)) + terminator


def fit(
    target: int,
    tolerance: float,
    make: Callable[[int], bytes],
    n0: int,
    n_min: int,
    n_max: int,
    max_iter: int = 12,
) -> tuple[int, bytes]:
    """Find ``n`` such that ``len(make(n))`` is within ``tolerance`` of ``target``.

    ``make`` must be monotone in ``n``: more of the parameter, more bytes. The search
    scales ``n`` proportionally (a secant step), and switches to bisection as soon as it
    has a bracket, which keeps it from oscillating when ``make`` is lumpy — a zip whose
    size jumps a whole entry at a time, say.

    Returns the parameter and the bytes it produced, so the caller does not pay to build
    the file twice. Raises :class:`SizingError` with the closest attempt if it cannot
    converge, because publishing a fixture outside its size class is worse than failing.
    """
    if not n_min <= n0 <= n_max:
        raise SizingError(f"n0 {n0} is outside [{n_min}, {n_max}]")
    if target <= 0:
        raise SizingError("target must be positive")

    allowed = tolerance * target
    low, high = n_min, n_max
    n = n0
    best: tuple[int, int, bytes] | None = None  # (error, n, payload)
    tried: set[int] = set()

    for _ in range(max_iter):
        payload = make(n)
        size = len(payload)
        error = abs(size - target)
        if best is None or error < best[0]:
            best = (error, n, payload)
        if error <= allowed:
            return n, payload

        tried.add(n)
        if size < target:
            low = max(low, n + 1)
        else:
            high = min(high, n - 1)
        if low > high:
            break

        # Secant step: assume size scales with n.
        projected = round(n * target / size) if size > 0 else high
        candidate = min(max(projected, low), high)
        if candidate in tried:
            candidate = (low + high) // 2  # bisect out of a repeat
        if candidate in tried:
            break
        n = candidate

    if best is None:  # unreachable: max_iter >= 1 always records an attempt
        raise SizingError("fit made no attempts; max_iter must be at least 1")
    error, best_n, best_payload = best
    raise SizingError(
        f"could not reach {target} bytes within {allowed:.0f} in {max_iter} attempts; "
        f"closest was n={best_n} at {len(best_payload)} bytes (off by {error})"
    )
