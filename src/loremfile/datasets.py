"""The shared synthetic datasets: people, orders, products (docs/05 §2).

**The prefix property.** Rows come from one RNG stream per dataset, generated in order,
so ``people-10`` is the first 10 rows of ``people-1000``, which is the first 1000 rows of
``people-100k``. Cross-format tests rely on it: the same row must appear identically in
CSV, JSON, Parquet, Avro and SQLite. Anything that consumes a row must therefore not
change how many draws it makes from the stream.

Nobody is identified. Names are common facts combined at random with invented emails
(``@example.com``/``@example.org``), reserved fiction phone ranges (US ``555-01xx``, UK
``+44 7700 900xxx``), invented street names and invented biographies. At 100,000 rows a
common name will coincide with a real person's; every other field is fabricated, which
is the reading of the content policy in docs/13 §5.
"""

from __future__ import annotations

import datetime as dt
import functools
import hashlib
import random
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from loremfile.util import lorem

WORDLISTS = Path(__file__).resolve().parent / "data" / "wordlists"

DatasetName = Literal["people", "orders", "products"]

#: Share of people rows with a negative balance, and share marked active.
NEGATIVE_BALANCE_SHARE = 0.05
ACTIVE_SHARE = 0.80

#: Every value a `bio` can contain is encodable in ISO-8859-1 and Windows-1252, so the
#: same rows serialise into every charset variant of the CSV fixtures.
BIO_MAX_CHARS = 200

TAG_VOCABULARY = (
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "zeta",
    "eta",
    "theta",
    "iota",
    "kappa",
    "lambda",
    "mu",
)
CURRENCIES = ("USD", "EUR", "GBP", "JPY", "INR", "BRL")
ORDER_STATUSES = ("pending", "paid", "shipped", "cancelled", "refunded")
ORDER_STATUS_WEIGHTS = (10, 50, 30, 5, 5)
PRODUCT_CATEGORIES = (
    "hardware",
    "software",
    "stationery",
    "furniture",
    "kitchen",
    "outdoor",
    "audio",
    "lighting",
)
PRODUCT_COLOURS = ("black", "white", "slate", "sand", "olive", "cobalt", "amber", "plum")


def dataset_seed(name: str) -> bytes:
    """``sha256("loremfile:dataset:<name>")`` — one stream per dataset (docs/05 §2)."""
    return hashlib.sha256(f"loremfile:dataset:{name}".encode()).digest()


@functools.cache
def _wordlist(name: str) -> tuple[str, ...]:
    return tuple(WORDLISTS.joinpath(name).read_text(encoding="utf-8").splitlines())


@functools.lru_cache(maxsize=1)
def _cities() -> tuple[tuple[str, str], ...]:
    """(city, ISO-3166 alpha-2) pairs. The country always matches its city."""
    rows = _wordlist("cities.txt")
    return tuple((line.split("\t")[0], line.split("\t")[1]) for line in rows)


def _ascii_fold(value: str) -> str:
    """Reduce accented Latin-1 letters to ASCII, for email local parts."""
    table = str.maketrans(
        "àáâãäåçèéêëìíîïñòóôõöùúûüýÿœæøåÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜÝ",
        "aaaaaaceeeeiiiinooooouuuuyyeaoaAAAAAACEEEEIIIINOOOOOUUUUY",
    )
    return value.translate(table)


def _bio(rng: random.Random) -> str:
    """0-200 characters of lorem plus accented Latin-1 words, Latin-1 safe throughout."""
    length = rng.randint(0, BIO_MAX_CHARS)
    if length == 0:
        return ""
    pool = list(lorem.LOREM_WORDS) + list(_wordlist("latin1_words.txt"))
    out: list[str] = []
    size = 0
    while size < length:
        word = rng.choice(pool)
        out.append(word)
        size += len(word) + 1
    return " ".join(out)[:length].rstrip()


def _person(rng: random.Random, row_id: int) -> dict[str, Any]:
    first = rng.choice(_wordlist("first_names.txt"))
    last = rng.choice(_wordlist("last_names.txt"))
    city, country = rng.choice(_cities())
    domain = "example.org" if row_id % 10 == 0 else "example.com"
    local = _ascii_fold(f"{first}.{last}{row_id}").lower()
    # Reserved fiction ranges only.
    if country == "US":
        phone = f"+1-555-01{rng.randrange(100):02d}"
    else:
        phone = f"+44 7700 900{rng.randrange(1000):03d}"
    birth = dt.date(1950, 1, 1) + dt.timedelta(
        days=rng.randrange((dt.date(2005, 12, 31) - dt.date(1950, 1, 1)).days + 1)
    )
    signup = dt.datetime(2015, 1, 1, tzinfo=dt.UTC) + dt.timedelta(
        seconds=rng.randrange(
            int(
                (
                    dt.datetime(2019, 12, 31, 23, 59, 59, tzinfo=dt.UTC)
                    - dt.datetime(2015, 1, 1, tzinfo=dt.UTC)
                ).total_seconds()
            )
            + 1
        )
    )
    balance = Decimal(str(round(rng.lognormvariate(5.52, 1.0), 2)))
    if rng.random() < NEGATIVE_BALANCE_SHARE:
        balance = -balance
    return {
        "id": row_id,
        "first_name": first,
        "last_name": last,
        "email": f"{local}@{domain}",
        "phone": phone,
        "street": f"{rng.randint(1, 9999)} {rng.choice(_wordlist('streets.txt'))}",
        "city": city,
        "country": country,
        "birth_date": birth,
        "signup_at": signup,
        "balance": balance,
        "is_active": rng.random() < ACTIVE_SHARE,
        "tags": rng.sample(TAG_VOCABULARY, rng.randint(0, 3)),
        "bio": _bio(rng),
    }


def _order(rng: random.Random, row_id: int) -> dict[str, Any]:
    created = dt.datetime(2019, 1, 1, tzinfo=dt.UTC) + dt.timedelta(
        seconds=rng.randrange(365 * 24 * 3600)
    )
    return {
        "order_id": row_id,
        "person_id": rng.randint(1, 1000),
        "amount": Decimal(str(round(rng.uniform(1.00, 2000.00), 2))),
        "currency": rng.choice(CURRENCIES),
        "status": rng.choices(ORDER_STATUSES, weights=ORDER_STATUS_WEIGHTS, k=1)[0],
        "created_at": created,
    }


def _product(rng: random.Random, row_id: int) -> dict[str, Any]:
    name = " ".join(w.capitalize() for w in lorem.words(rng, 2))
    return {
        "sku": f"LF-{row_id:05d}",
        "name": name,
        "category": rng.choice(PRODUCT_CATEGORIES),
        "price": Decimal(str(round(rng.uniform(1.00, 999.99), 2))),
        "stock": rng.randint(0, 500),
        "attributes": {
            "color": rng.choice(PRODUCT_COLOURS),
            "weight_g": rng.randint(10, 5000),
            "dimensions_mm": {
                "w": rng.randint(10, 600),
                "h": rng.randint(10, 600),
                "d": rng.randint(10, 600),
            },
            "tags": rng.sample(TAG_VOCABULARY, rng.randint(0, 3)),
        },
    }


_BUILDERS = {"people": _person, "orders": _order, "products": _product}


def rows(name: DatasetName, count: int) -> list[dict[str, Any]]:
    """The first ``count`` rows of a dataset.

    Rows are generated sequentially from one stream, so a smaller request is always a
    prefix of a larger one. Do not reorder or skip draws inside a row builder without
    accepting that every published fixture using that dataset would change — which the
    manifest lock rule forbids.
    """
    if name not in _BUILDERS:
        raise KeyError(f"unknown dataset '{name}'")
    if count < 0:
        raise ValueError("count must not be negative")
    rng = random.Random(dataset_seed(name))  # noqa: S311 - reproducibility, not crypto
    build = _BUILDERS[name]
    return [build(rng, row_id) for row_id in range(1, count + 1)]


@functools.lru_cache(maxsize=8)
def _cached(name: DatasetName, count: int) -> tuple[dict[str, Any], ...]:
    return tuple(rows(name, count))


def cached_rows(name: DatasetName, count: int) -> list[dict[str, Any]]:
    """``rows`` with an in-process cache, so one build generates each dataset once."""
    return [dict(row) for row in _cached(name, count)]
