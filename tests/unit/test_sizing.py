"""M1.7: size tokens, size classes and the fit search (docs/05 §4 and §6)."""

from __future__ import annotations

import pytest

from loremfile.util.sizing import (
    SizingError,
    fit,
    pad_to,
    parse_size_token,
    size_matches,
)


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("1kb", 1_000),
        ("10mb", 10_000_000),
        ("1gb", 1_000_000_000),
        ("1kib", 1_024),
        ("10mib", 10_485_760),
        ("10mib-plus-1", 10_485_761),
        ("10mb-minus-1", 9_999_999),
        ("512b", 512),
    ],
)
def test_size_tokens(token: str, expected: int) -> None:
    assert parse_size_token(token) == expected


def test_decimal_and_binary_units_really_differ() -> None:
    """The whole point of the kb/kib distinction in the naming grammar."""
    assert parse_size_token("10mb") != parse_size_token("10mib")


@pytest.mark.parametrize("token", ["a4", "3pages", "720p", "", "10", "10tb", "10mbx"])
def test_non_size_tokens_return_none(token: str) -> None:
    assert parse_size_token(token) is None


# --- size classes ----------------------------------------------------------


def test_exact_requires_the_exact_byte_count() -> None:
    assert size_matches(1000, "exact", 1000)
    assert not size_matches(1001, "exact", 1000)


def test_boundary_is_exactly_one_byte_either_way() -> None:
    assert size_matches(1001, "boundary", 1000)
    assert size_matches(999, "boundary", 1000)
    assert not size_matches(1000, "boundary", 1000)
    assert not size_matches(1002, "boundary", 1000)


def test_approx_is_five_percent() -> None:
    assert size_matches(1050, "approx", 1000)
    assert size_matches(950, "approx", 1000)
    assert not size_matches(1051, "approx", 1000)


def test_free_accepts_anything() -> None:
    assert size_matches(123456789, "free", None)


def test_sized_classes_need_a_nominal() -> None:
    with pytest.raises(SizingError, match="needs nominal_bytes"):
        size_matches(10, "exact", None)


def test_unknown_size_class_is_an_error() -> None:
    with pytest.raises(SizingError, match="unknown size_class"):
        size_matches(10, "roughly", 10)


# --- padding ---------------------------------------------------------------


def test_pad_to_hits_the_target_exactly_and_ends_with_a_newline() -> None:
    out = pad_to(b"lorem ipsum", 64)
    assert len(out) == 64
    assert out.endswith(b"\n")
    assert out.startswith(b"lorem ipsum")


def test_pad_to_truncates_when_the_payload_is_too_long() -> None:
    out = pad_to(b"x" * 100, 10)
    assert len(out) == 10
    assert out.endswith(b"\n")


def test_pad_to_rejects_an_impossible_target() -> None:
    with pytest.raises(SizingError, match="smaller than the terminator"):
        pad_to(b"x", 0)


# --- fit -------------------------------------------------------------------


def linear(n: int) -> bytes:
    """A perfectly proportional builder: 10 bytes per unit."""
    return b"x" * (n * 10)


def with_overhead(n: int) -> bytes:
    """Realistic: a fixed header plus per-unit content, like a container format."""
    return b"H" * 137 + b"y" * (n * 33)


def lumpy(n: int) -> bytes:
    """Size jumps in blocks, like a zip gaining a whole entry at a time."""
    return b"z" * (((n * 7) // 100) * 100)


def test_fit_finds_an_exact_proportional_target() -> None:
    n, payload = fit(10_000, 0.0, linear, n0=1, n_min=1, n_max=100_000)
    assert len(payload) == 10_000
    assert n == 1000


def test_fit_converges_with_overhead() -> None:
    target = 50_000
    _, payload = fit(target, 0.05, with_overhead, n0=1, n_min=1, n_max=100_000)
    assert abs(len(payload) - target) <= 0.05 * target


def test_fit_converges_on_a_lumpy_builder() -> None:
    target = 20_000
    _, payload = fit(target, 0.05, lumpy, n0=1, n_min=1, n_max=1_000_000)
    assert abs(len(payload) - target) <= 0.05 * target


def test_fit_returns_the_bytes_so_the_caller_does_not_rebuild() -> None:
    n, payload = fit(1_000, 0.05, linear, n0=1, n_min=1, n_max=10_000)
    assert payload == linear(n)


def test_fit_raises_rather_than_publishing_a_wrong_size() -> None:
    """A fixture is never published outside its size class."""
    with pytest.raises(SizingError, match="could not reach"):
        # Impossible: the builder is clamped far below the target.
        fit(1_000_000, 0.0, linear, n0=1, n_min=1, n_max=10)


def test_fit_error_names_the_closest_attempt() -> None:
    with pytest.raises(SizingError) as excinfo:
        fit(1_000_000, 0.0, linear, n0=1, n_min=1, n_max=10)
    assert "closest was" in str(excinfo.value)


def test_fit_rejects_a_start_outside_the_bounds() -> None:
    with pytest.raises(SizingError, match="outside"):
        fit(100, 0.05, linear, n0=999, n_min=1, n_max=10)


def test_fit_rejects_a_nonsense_target() -> None:
    with pytest.raises(SizingError, match="target must be positive"):
        fit(0, 0.05, linear, n0=1, n_min=1, n_max=10)


def test_fit_is_deterministic() -> None:
    first = fit(50_000, 0.05, with_overhead, n0=1, n_min=1, n_max=100_000)
    second = fit(50_000, 0.05, with_overhead, n0=1, n_min=1, n_max=100_000)
    assert first == second


def test_fit_does_not_exceed_max_iter_calls() -> None:
    calls = 0

    def counted(n: int) -> bytes:
        nonlocal calls
        calls += 1
        return with_overhead(n)

    with pytest.raises(SizingError):
        fit(10**9, 0.0, counted, n0=1, n_min=1, n_max=10, max_iter=5)
    assert calls <= 5
