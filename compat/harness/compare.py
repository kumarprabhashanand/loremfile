"""Reported against expected: the only place a value is judged.

The harness compares only names present on both sides. One tolerance exists anywhere
(`scope.tolerance`, 1 ms of duration), and one translation: a CSV reader returns every record,
the header among them, where the manifest's `rows` counts data rows, so the expected count is
`rows` plus one when the manifest says the file has a header.
"""

from __future__ import annotations

from typing import Any


def comparable(fmt: str, expect: dict[str, Any]) -> dict[str, Any]:
    """The manifest's values as a reader of this format should report them."""
    values = {name: value for name, value in expect.items() if name != "has_header"}
    if fmt == "csv" and "rows" in values and expect.get("has_header"):
        values["rows"] = values["rows"] + 1
    return values


def same(name: str, reported: Any, expected: Any, tolerance: dict[str, int]) -> bool:  # noqa: ANN401
    if isinstance(reported, bool) or isinstance(expected, bool):
        return isinstance(reported, bool) and isinstance(expected, bool) and reported == expected
    if (
        name in tolerance
        and isinstance(reported, int | float)
        and isinstance(expected, int | float)
    ):
        return abs(reported - expected) <= tolerance[name]
    return bool(reported == expected)


def differences(
    fmt: str, reported: dict[str, Any], expect: dict[str, Any], tolerance: dict[str, int]
) -> dict[str, dict[str, Any]]:
    """{name: {"reported": r, "expected": e}} for each name both sides hold and that disagrees."""
    wanted = comparable(fmt, expect)
    return {
        name: {"reported": reported[name], "expected": wanted[name]}
        for name in sorted(reported.keys() & wanted.keys())
        if not same(name, reported[name], wanted[name], tolerance)
    }


def compared(fmt: str, reported: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    return sorted(reported.keys() & comparable(fmt, expect).keys())
