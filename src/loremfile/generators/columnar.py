"""Columnar and database fixtures — parquet, avro, arrow, sqlite (docs/05 §3.7).

These are the formats where determinism is hardest to get, because each writer embeds
metadata of its own: Parquet records a ``created_by`` version string, Avro writes a
random sync marker, and SQLite stamps a library version and a change counter into the
file header. The toolchain pin covers the version strings; the determinism guard covers
the randomness; and SQLite gets an explicit ``VACUUM`` so the page layout does not depend
on the order rows happened to be inserted.
"""

from __future__ import annotations

import io
import sqlite3
import tempfile
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import fastavro
import pyarrow
import pyarrow.parquet

from loremfile.generators.base import GeneratorContext, generator
from loremfile.generators.data import PEOPLE_COLUMNS

#: One row group for every fixture here, so `row_groups` is a stable published prop
#: rather than a function of how pyarrow happened to chunk the input.
ROW_GROUP_SIZE = 1_000_000

AVRO_SCHEMA: dict[str, Any] = {
    "type": "record",
    "name": "Person",
    "namespace": "dev.loremfile",
    "fields": [
        {"name": "id", "type": "int"},
        {"name": "first_name", "type": "string"},
        {"name": "last_name", "type": "string"},
        {"name": "email", "type": "string"},
        {"name": "phone", "type": ["null", "string"]},
        {"name": "street", "type": ["null", "string"]},
        {"name": "city", "type": ["null", "string"]},
        {"name": "country", "type": ["null", "string"]},
        {"name": "birth_date", "type": {"type": "int", "logicalType": "date"}},
        {
            "name": "signup_at",
            "type": {"type": "long", "logicalType": "timestamp-micros"},
        },
        {"name": "balance", "type": "double"},
        {"name": "is_active", "type": "boolean"},
        {"name": "tags", "type": {"type": "array", "items": "string"}},
        {"name": "bio", "type": ["null", "string"]},
    ],
}


def _columns(rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """The people rows as columns, with types Arrow and Avro both understand."""
    out: dict[str, list[Any]] = {name: [] for name in PEOPLE_COLUMNS}
    for row in rows:
        for name in PEOPLE_COLUMNS:
            value = row[name]
            if isinstance(value, Decimal):
                value = float(value)
            out[name].append(value)
    return out


def _arrow_table(rows: list[dict[str, Any]]) -> pyarrow.Table:
    columns = _columns(rows)
    schema = pyarrow.schema(
        [
            ("id", pyarrow.int32()),
            ("first_name", pyarrow.string()),
            ("last_name", pyarrow.string()),
            ("email", pyarrow.string()),
            ("phone", pyarrow.string()),
            ("street", pyarrow.string()),
            ("city", pyarrow.string()),
            ("country", pyarrow.string()),
            ("birth_date", pyarrow.date32()),
            ("signup_at", pyarrow.timestamp("us", tz="UTC")),
            ("balance", pyarrow.float64()),
            ("is_active", pyarrow.bool_()),
            ("tags", pyarrow.list_(pyarrow.string())),
            ("bio", pyarrow.string()),
        ]
    )
    return pyarrow.Table.from_pydict(columns, schema=schema)


def _parquet_bytes(table: pyarrow.Table, *, compression: str, row_group_size: int) -> bytes:
    """``store_schema=False`` for the pandas metadata block: it would otherwise embed a
    pandas version string, which the toolchain pin does not cover because pandas is not
    a dependency at all."""
    sink = pyarrow.BufferOutputStream()
    pyarrow.parquet.write_table(
        table,
        sink,
        compression=compression,
        row_group_size=row_group_size,
        store_schema=False,
        write_statistics=True,
        version="2.6",
    )
    return bytes(sink.getvalue())


@generator(parallel_safe=False)
def parquet_people(
    ctx: GeneratorContext,
    *,
    rows: int,
    compression: str = "snappy",
    row_group_size: int = ROW_GROUP_SIZE,
) -> bytes:
    """The people dataset as Parquet; `row_group_size` below `rows` splits it into groups."""
    table = _arrow_table(ctx.dataset("people", rows))
    return _parquet_bytes(table, compression=compression, row_group_size=row_group_size)


@generator(parallel_safe=False)
def parquet_nested(ctx: GeneratorContext, *, rows: int) -> bytes:
    """The same people reshaped: name and address as structs, contacts as a map.

    The flat people files already hold one list column (`tags`); what this adds is the
    two nested types a reader that flattens to scalars and lists cannot represent.
    """
    people = ctx.dataset("people", rows)
    text = pyarrow.string()
    name = pyarrow.struct([("first", text), ("last", text)])
    address = pyarrow.struct([("street", text), ("city", text), ("country", text)])
    schema = pyarrow.schema(
        [
            ("id", pyarrow.int32()),
            ("name", name),
            ("address", address),
            ("contacts", pyarrow.map_(text, text)),
            ("tags", pyarrow.list_(text)),
        ]
    )
    columns = {
        "id": [p["id"] for p in people],
        "name": [{"first": p["first_name"], "last": p["last_name"]} for p in people],
        "address": [
            {"street": p["street"], "city": p["city"], "country": p["country"]} for p in people
        ],
        "contacts": [[("email", p["email"]), ("phone", p["phone"])] for p in people],
        "tags": [p["tags"] for p in people],
    }
    table = pyarrow.Table.from_pydict(columns, schema=schema)
    return _parquet_bytes(table, compression="snappy", row_group_size=ROW_GROUP_SIZE)


@generator(parallel_safe=False)
def arrow_people(
    ctx: GeneratorContext,
    *,
    rows: int,
    ipc: str = "file",
    compression: str | None = None,
    batch_rows: int | None = None,
) -> bytes:
    """The people dataset in Arrow IPC: the *file* format by default, or the stream format.

    `compression` compresses every buffer (`zstd` or `lz4`), single-threaded so the order
    of work cannot reach the bytes; `batch_rows` splits the rows into record batches. With
    neither, the call is exactly the one `people-1000.arrow` was published from.
    """
    table = _arrow_table(ctx.dataset("people", rows))
    options = (
        pyarrow.ipc.IpcWriteOptions(compression=compression, use_threads=False)
        if compression
        else None
    )
    opener = {"file": pyarrow.ipc.new_file, "stream": pyarrow.ipc.new_stream}[ipc]
    sink = pyarrow.BufferOutputStream()
    with opener(sink, table.schema, options=options) as writer:
        writer.write_table(table, max_chunksize=batch_rows)
    return bytes(sink.getvalue())


#: Words for the string-valued columns of the all-types table: Lorem Ipsum, never data.
LOREM = ("lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing", "elit")
#: 2020-01-01T00:00:00Z, the clock every generator sees (docs/05 §1 rule 2).
EPOCH_US = 1_577_836_800_000_000


@generator(parallel_safe=False)
def arrow_all_types(ctx: GeneratorContext, *, rows: int, null_every: int) -> bytes:
    """One column per type a reader is likely to get wrong, every column with nulls.

    Nested (list, struct, map), dictionary-encoded, decimal, timezone-aware timestamp,
    date, time of day and binary. Values come from the fixture's seed; every
    `null_every`-th row is null in every column, so each column's null count is the same
    measured number.
    """
    rng = ctx.rng

    def maybe(index: int, value: Any) -> Any:  # noqa: ANN401 - one value of any column type
        return None if index % null_every == null_every - 1 else value

    words = [LOREM[rng.randrange(len(LOREM))] for _ in range(rows)]
    columns = {
        "list_int32": pyarrow.array(
            [maybe(i, [rng.randrange(1000) for _ in range(i % 4)]) for i in range(rows)],
            pyarrow.list_(pyarrow.int32()),
        ),
        "struct": pyarrow.array(
            [maybe(i, {"x": rng.randrange(1000), "word": words[i]}) for i in range(rows)],
            pyarrow.struct([("x", pyarrow.int32()), ("word", pyarrow.string())]),
        ),
        "map_string_int32": pyarrow.array(
            [maybe(i, [(words[i], rng.randrange(1000))]) for i in range(rows)],
            pyarrow.map_(pyarrow.string(), pyarrow.int32()),
        ),
        "dictionary_string": pyarrow.array(
            [maybe(i, words[i]) for i in range(rows)], pyarrow.string()
        ).dictionary_encode(),
        "decimal128": pyarrow.array(
            [maybe(i, Decimal(rng.randrange(10**6)) / 100) for i in range(rows)],
            pyarrow.decimal128(18, 2),
        ),
        "timestamp_utc": pyarrow.array(
            [maybe(i, EPOCH_US + rng.randrange(10**12)) for i in range(rows)],
            pyarrow.timestamp("us", tz="UTC"),
        ),
        "date32": pyarrow.array(
            [maybe(i, 18262 + rng.randrange(3650)) for i in range(rows)], pyarrow.date32()
        ),
        "time64_us": pyarrow.array(
            [maybe(i, rng.randrange(86_400 * 10**6)) for i in range(rows)], pyarrow.time64("us")
        ),
        "binary": pyarrow.array(
            [maybe(i, bytes(rng.randrange(256) for _ in range(4))) for i in range(rows)],
            pyarrow.binary(),
        ),
    }
    table = pyarrow.table(columns)
    sink = pyarrow.BufferOutputStream()
    with pyarrow.ipc.new_file(sink, table.schema) as writer:
        writer.write_table(table)
    return bytes(sink.getvalue())


@generator(parallel_safe=False)
def avro_people(ctx: GeneratorContext, *, rows: int) -> bytes:
    """The people dataset as Avro.

    The sync marker is passed explicitly rather than left to fastavro.

    docs/06 §4 assumed the marker would come from the patched ``random``. It does not:
    ``fastavro._write`` is a compiled C extension, so it draws its randomness below the
    Python layer where ``util.determinism`` cannot reach, and two builds produced
    different bytes. That is the exact failure mode docs/06 §4 anticipates, and its
    prescribed remedy — "pass an explicit IV/salt where the library API allows it" —
    is what this does. The marker is derived from the fixture's own seed, so it is
    stable for this path and differs from every other fixture's.
    """
    records = []
    for row in ctx.dataset("people", rows):
        record = {name: row[name] for name in PEOPLE_COLUMNS}
        record["balance"] = float(record["balance"])
        records.append(record)
    buffer = io.BytesIO()
    fastavro.writer(buffer, AVRO_SCHEMA, records, codec="deflate", sync_marker=ctx.stream(16))
    return buffer.getvalue()


# --- sqlite ----------------------------------------------------------------


def _sqlite_bytes(build: Callable[[sqlite3.Connection], None], workdir: Path) -> bytes:
    """Run ``build(connection)`` against a fresh database and return its bytes.

    The pragmas and the closing ``VACUUM`` are what make the file reproducible: a fixed
    page size, no write-ahead log, and a page layout that depends on the final contents
    rather than on the order rows were inserted.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workdir) as temporary:
        path = Path(temporary) / "fixture.sqlite"
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA page_size=4096")
            connection.execute("PRAGMA journal_mode=DELETE")
            build(connection)
            connection.commit()
            connection.execute("VACUUM")
            connection.commit()
        finally:
            connection.close()
        return path.read_bytes()


def _people_values(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    out = []
    for row in rows:
        out.append(
            (
                row["id"],
                row["first_name"],
                row["last_name"],
                row["email"],
                row["phone"],
                row["street"],
                row["city"],
                row["country"],
                row["birth_date"].isoformat(),
                row["signup_at"].isoformat().replace("+00:00", "Z"),
                float(row["balance"]),
                1 if row["is_active"] else 0,
                "|".join(row["tags"]),
                row["bio"],
            )
        )
    return out


PEOPLE_DDL = """
CREATE TABLE people (
  id INTEGER PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
  email TEXT NOT NULL, phone TEXT, street TEXT, city TEXT, country TEXT,
  birth_date TEXT, signup_at TEXT, balance REAL, is_active INTEGER,
  tags TEXT, bio TEXT
)
"""
# S608: the only interpolation is the count of "?" placeholders; every value is bound.
PEOPLE_INSERT = f"INSERT INTO people VALUES ({', '.join('?' * len(PEOPLE_COLUMNS))})"  # noqa: S608


@generator(parallel_safe=False)
def sqlite_people(ctx: GeneratorContext, *, rows: int) -> bytes:
    """A single-table database holding the people dataset."""
    values = _people_values(ctx.dataset("people", rows))

    def build(connection: sqlite3.Connection) -> None:
        connection.execute(PEOPLE_DDL)
        connection.executemany(PEOPLE_INSERT, values)

    return _sqlite_bytes(build, ctx.workdir)


@generator(parallel_safe=False)
def sqlite_multi_table(ctx: GeneratorContext, *, people: int = 200, orders: int = 500) -> bytes:
    """Three tables with a foreign key, two indexes, a view and a trigger.

    The shape a schema inspector should be tested against, rather than a single flat
    table that exercises nothing.
    """
    people_values = _people_values(ctx.dataset("people", people))
    order_rows = ctx.dataset("orders", orders)
    product_rows = ctx.dataset("products", 100)

    def build(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(PEOPLE_DDL)
        connection.execute(
            """
            CREATE TABLE orders (
              order_id INTEGER PRIMARY KEY, person_id INTEGER NOT NULL,
              amount REAL NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (person_id) REFERENCES people(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE products (
              sku TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
              price REAL NOT NULL, stock INTEGER NOT NULL
            )
            """
        )
        connection.execute("CREATE TABLE audit (id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
        connection.executemany(PEOPLE_INSERT, people_values)
        connection.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    o["order_id"],
                    # Keep every foreign key valid against the people actually inserted.
                    (o["person_id"] - 1) % len(people_values) + 1,
                    float(o["amount"]),
                    o["currency"],
                    o["status"],
                    o["created_at"].isoformat().replace("+00:00", "Z"),
                )
                for o in order_rows
            ],
        )
        connection.executemany(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?)",
            [
                (p["sku"], p["name"], p["category"], float(p["price"]), p["stock"])
                for p in product_rows
            ],
        )
        connection.execute("CREATE INDEX idx_orders_person ON orders(person_id)")
        connection.execute("CREATE INDEX idx_people_country ON people(country)")
        connection.execute(
            """
            CREATE VIEW order_totals AS
            SELECT p.id AS person_id, p.email AS email,
                   COUNT(o.order_id) AS order_count, COALESCE(SUM(o.amount), 0) AS total
            FROM people p LEFT JOIN orders o ON o.person_id = p.id
            GROUP BY p.id, p.email
            """
        )
        # A fixed note, not generated text: nothing is interpolated into the
        # trigger body, so there is no quoting question and a schema inspector
        # reading this fixture sees a predictable string.
        connection.execute(
            """
            CREATE TRIGGER orders_audit AFTER INSERT ON orders
            BEGIN
              INSERT INTO audit (note) VALUES ('order inserted');
            END
            """
        )

    return _sqlite_bytes(build, ctx.workdir)
