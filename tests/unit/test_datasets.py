"""M1.7: the shared datasets and their prefix property (docs/05 §2).

The prefix property is load-bearing: cross-format tests assert that the same row
appears identically in CSV, JSON, Parquet, Avro and SQLite, and the published bytes of
every dataset fixture depend on it. Breaking it would change fixtures that are already
published, which the manifest lock rule forbids.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

import pytest

from loremfile import datasets


@pytest.mark.parametrize(
    ("name", "small", "large"),
    [("people", 10, 1000), ("orders", 100, 1000), ("products", 10, 100)],
)
def test_prefix_property(name: str, small: int, large: int) -> None:
    assert datasets.rows(name, small) == datasets.rows(name, large)[:small]  # type: ignore[arg-type]


def test_people_prefix_chain_matches_the_published_sizes() -> None:
    """people-10 ⊂ people-1000 ⊂ people-100k, as docs/05 §2 promises."""
    thousand = datasets.rows("people", 1000)
    assert datasets.rows("people", 10) == thousand[:10]
    assert thousand[:100] == datasets.rows("people", 100)


@pytest.mark.parametrize("name", ["people", "orders", "products"])
def test_generation_is_deterministic(name: str) -> None:
    assert datasets.rows(name, 25) == datasets.rows(name, 25)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["people", "orders", "products"])
def test_zero_rows_is_allowed(name: str) -> None:
    assert datasets.rows(name, 0) == []  # type: ignore[arg-type]


def test_unknown_dataset_is_rejected() -> None:
    with pytest.raises(KeyError, match="unknown dataset"):
        datasets.rows("penguins", 1)  # type: ignore[arg-type]


def test_negative_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        datasets.rows("people", -1)


def test_datasets_have_distinct_seeds() -> None:
    seeds = {datasets.dataset_seed(n) for n in ("people", "orders", "products")}
    assert len(seeds) == 3


# --- content policy (docs/13 §5) ------------------------------------------


PEOPLE = datasets.rows("people", 1000)


def test_ids_are_sequential_from_one() -> None:
    assert [row["id"] for row in PEOPLE[:5]] == [1, 2, 3, 4, 5]


def test_emails_are_example_domains_only() -> None:
    assert all(row["email"].endswith(("@example.com", "@example.org")) for row in PEOPLE)


def test_every_tenth_row_uses_example_org() -> None:
    assert PEOPLE[9]["email"].endswith("@example.org")
    assert PEOPLE[0]["email"].endswith("@example.com")


def test_emails_are_ascii_so_every_charset_variant_can_hold_them() -> None:
    assert all(row["email"].isascii() for row in PEOPLE)


def test_phones_use_reserved_fiction_ranges_only() -> None:
    us = re.compile(r"^\+1-555-01\d{2}$")
    uk = re.compile(r"^\+44 7700 900\d{3}$")
    assert all(us.match(row["phone"]) or uk.match(row["phone"]) for row in PEOPLE)


def test_country_always_matches_its_city() -> None:
    pairs = {(row["city"], row["country"]) for row in PEOPLE}
    cities = [city for city, _ in pairs]
    assert len(cities) == len(set(cities)), "a city must map to exactly one country"


def test_bio_is_latin1_and_windows1252_safe() -> None:
    """The same rows must serialise into every charset variant of the CSV fixtures."""
    for row in PEOPLE:
        row["bio"].encode("iso-8859-1")
        row["bio"].encode("windows-1252")


def test_bio_respects_its_length_cap() -> None:
    assert all(len(row["bio"]) <= datasets.BIO_MAX_CHARS for row in PEOPLE)


def test_every_field_of_a_person_is_present_and_typed() -> None:
    row = PEOPLE[0]
    assert isinstance(row["id"], int)
    assert isinstance(row["birth_date"], dt.date)
    assert isinstance(row["signup_at"], dt.datetime)
    assert row["signup_at"].tzinfo is dt.UTC
    assert isinstance(row["balance"], Decimal)
    assert isinstance(row["is_active"], bool)
    assert isinstance(row["tags"], list)


def test_dates_stay_in_their_documented_ranges() -> None:
    for row in PEOPLE:
        assert dt.date(1950, 1, 1) <= row["birth_date"] <= dt.date(2005, 12, 31)
        assert (
            dt.datetime(2015, 1, 1, tzinfo=dt.UTC)
            <= row["signup_at"]
            <= dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
        )


def test_tags_come_from_the_fixed_vocabulary() -> None:
    for row in PEOPLE:
        assert set(row["tags"]) <= set(datasets.TAG_VOCABULARY)
        assert len(row["tags"]) <= 3


def test_some_balances_are_negative_and_most_people_are_active() -> None:
    """Sanity on the documented distributions, loosely enough not to be brittle."""
    negative = sum(1 for row in PEOPLE if row["balance"] < 0)
    active = sum(1 for row in PEOPLE if row["is_active"])
    assert 0 < negative < len(PEOPLE) * 0.15
    assert len(PEOPLE) * 0.7 < active < len(PEOPLE) * 0.9


# --- orders and products ---------------------------------------------------


def test_orders_fields() -> None:
    orders = datasets.rows("orders", 200)
    assert [o["order_id"] for o in orders[:3]] == [1, 2, 3]
    assert all(o["currency"] in datasets.CURRENCIES for o in orders)
    assert all(o["status"] in datasets.ORDER_STATUSES for o in orders)
    assert all(1 <= o["person_id"] <= 1000 for o in orders)
    assert all(Decimal("1.00") <= o["amount"] <= Decimal("2000.00") for o in orders)
    assert all(o["created_at"].year == 2019 for o in orders)


def test_products_fields() -> None:
    products = datasets.rows("products", 100)
    assert products[0]["sku"] == "LF-00001"
    assert products[99]["sku"] == "LF-00100"
    assert all(p["category"] in datasets.PRODUCT_CATEGORIES for p in products)
    assert all(0 <= p["stock"] <= 500 for p in products)
    attributes = products[0]["attributes"]
    assert set(attributes) == {"color", "weight_g", "dimensions_mm", "tags"}
    assert set(attributes["dimensions_mm"]) == {"w", "h", "d"}


# --- caching ---------------------------------------------------------------


def test_cached_rows_matches_rows_and_hands_back_copies() -> None:
    cached = datasets.cached_rows("people", 5)
    assert cached == datasets.rows("people", 5)
    cached[0]["first_name"] = "MUTATED"
    assert datasets.cached_rows("people", 5)[0]["first_name"] != "MUTATED"
