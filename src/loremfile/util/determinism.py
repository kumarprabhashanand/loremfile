"""Pin every ambient source of nondeterminism for the duration of a generator call.

docs/06 §4. These sources are **patched, not forbidden**: third-party libraries reach
for ``os.urandom`` and the clock on their own (pyzipper's AES salt, fpdf2's encryption
IV, py7zr's timestamps, fastavro's sync marker), and raising would simply make those
formats ungeneratable. Patching makes them draw from a stream seeded by the fixture's
own path, so the same fixture always produces the same bytes.

Generators themselves still use ``ctx.rng``. A unit test greps the generator modules for
``random.`` and ``datetime.now`` and fails on a hit, so the patches stay a safety net for
libraries rather than a licence for our own code.

The patches apply only inside ``loremfile build``. ``manifest update`` and ``verify-live``
run unpatched and legitimately use the clock.
"""

from __future__ import annotations

import contextlib
import datetime as _datetime
import hashlib
import os
import random
import secrets
import time
import uuid
from collections.abc import Iterator
from typing import Self
from unittest import mock

from loremfile.config import SOURCE_DATE_EPOCH

#: The single instant every clock reports inside a generator.
FIXED_DATETIME = _datetime.datetime.fromtimestamp(SOURCE_DATE_EPOCH, tz=_datetime.UTC)


class SeededByteStream:
    """An endless, reproducible byte stream from SHAKE-256.

    SHAKE-256 is an extendable-output function, so one seed yields as many bytes as a
    build asks for without the caller tracking counters.
    """

    def __init__(self, seed: bytes) -> None:
        self._seed = seed
        self._buffer = b""
        self._block = 0

    def read(self, size: int) -> bytes:
        if size < 0:
            raise ValueError("size must not be negative")
        while len(self._buffer) < size:
            self._buffer += hashlib.shake_256(self._seed + self._block.to_bytes(8, "big")).digest(
                4096
            )
            self._block += 1
        out, self._buffer = self._buffer[:size], self._buffer[size:]
        return out


def seed_for(path: str) -> bytes:
    """``sha256("loremfile:" + path)`` — the seed every generator receives (docs/05 §1)."""
    return hashlib.sha256(f"loremfile:{path}".encode()).digest()


class _FixedDatetime(_datetime.datetime):
    """``datetime`` whose ``now``/``utcnow``/``today`` are pinned to the epoch.

    The classmethods build through ``cls`` so the subclass's own type comes back, which
    is what ``datetime``'s signatures promise and what libraries doing arithmetic on the
    result expect.
    """

    @classmethod
    def _at_epoch(cls, tz: _datetime.tzinfo | None) -> Self:
        moment = FIXED_DATETIME if tz is None else FIXED_DATETIME.astimezone(tz)
        return cls(
            moment.year,
            moment.month,
            moment.day,
            moment.hour,
            moment.minute,
            moment.second,
            moment.microsecond,
            tz,
        )

    @classmethod
    def now(cls, tz: _datetime.tzinfo | None = None) -> Self:
        return cls._at_epoch(tz)

    @classmethod
    def utcnow(cls) -> Self:
        return cls._at_epoch(None)

    @classmethod
    def today(cls) -> Self:
        return cls._at_epoch(None)


@contextlib.contextmanager
def deterministic(seed: bytes) -> Iterator[SeededByteStream]:
    """Patch clocks, randomness and locale for the duration of the block.

    Yields the byte stream the patches draw from, so a caller can take bytes from the
    same reproducible source if it needs to.
    """
    stream = SeededByteStream(seed)
    # random's own Mersenne Twister is seeded from the same stream, so library code
    # calling module-level random.* is reproducible without being routed byte by byte.
    # S311: not cryptography. Reproducibility is the entire point here.
    module_random = random.Random(stream.read(32))  # noqa: S311

    def fake_urandom(size: int) -> bytes:
        return stream.read(size)

    def fake_uuid4() -> uuid.UUID:
        return uuid.UUID(bytes=stream.read(16), version=4)

    def fake_time() -> float:
        return float(SOURCE_DATE_EPOCH)

    def fake_time_ns() -> int:
        return SOURCE_DATE_EPOCH * 1_000_000_000

    previous_tz = os.environ.get("TZ")
    with contextlib.ExitStack() as stack:
        enter = stack.enter_context
        enter(mock.patch("os.urandom", fake_urandom))
        enter(mock.patch("secrets.token_bytes", lambda n=32: stream.read(n)))
        enter(mock.patch("secrets.token_hex", lambda n=32: stream.read(n).hex()))
        enter(mock.patch.object(secrets, "SystemRandom", lambda: module_random))
        enter(mock.patch("uuid.uuid4", fake_uuid4))
        enter(mock.patch("time.time", fake_time))
        enter(mock.patch("time.time_ns", fake_time_ns))
        enter(mock.patch.object(_datetime, "datetime", _FixedDatetime))
        # random.random and friends are module-level bound methods of a hidden
        # Random instance; swapping the instance's state is the reliable way.
        enter(mock.patch.object(random, "_inst", module_random))
        for name in (
            "random",
            "randint",
            "randrange",
            "choice",
            "choices",
            "shuffle",
            "sample",
            "uniform",
            "getrandbits",
            "randbytes",
        ):
            enter(mock.patch.object(random, name, getattr(module_random, name)))
        os.environ["TZ"] = "UTC"
        if hasattr(time, "tzset"):
            time.tzset()
        try:
            yield stream
        finally:
            if previous_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous_tz
            if hasattr(time, "tzset"):
                time.tzset()


def assert_environment() -> list[str]:
    """Check the process-level settings the container is supposed to provide.

    Returns a list of complaints; empty means the environment is as ``tools/Dockerfile``
    sets it. ``PYTHONHASHSEED`` cannot be set from inside a running interpreter, which is
    exactly why it belongs in the image rather than in code.
    """
    problems: list[str] = []
    expected: dict[str, str] = {
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
        "SOURCE_DATE_EPOCH": str(SOURCE_DATE_EPOCH),
    }
    for name, want in expected.items():
        got = os.environ.get(name)
        if got != want:
            problems.append(f"{name} is {got!r}, expected {want!r}")
    return problems
