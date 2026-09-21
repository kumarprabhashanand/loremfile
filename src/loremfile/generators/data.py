"""Data fixtures — csv, tsv, json, ndjson, xml, yaml, toml, sql (docs/05 §3.7).

All of these serialise the **same** shared `people` rows, so the same record can be
compared across formats — which is most of what makes them useful as fixtures. The
prefix property holds throughout: `people-10` is the first ten rows of `people-1000`.

Size-named fixtures here are `approx` and use `fit` on the row count (docs/05 §6), so a
1 MB CSV is still a prefix of the same dataset.
"""

from __future__ import annotations

import csv as csv_module
import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from loremfile.config import APPROX_TOLERANCE
from loremfile.generators.base import GeneratorContext, generator
from loremfile.util import lorem
from loremfile.util.sizing import fit

#: Column order for the people dataset, fixed so every format agrees.
PEOPLE_COLUMNS = (
    "id",
    "first_name",
    "last_name",
    "email",
    "phone",
    "street",
    "city",
    "country",
    "birth_date",
    "signup_at",
    "balance",
    "is_active",
    "tags",
    "bio",
)


def _scalar(value: object) -> str:
    """One value as text, the same way in every text format."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dt.datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, list):
        # Pipe-joined so the value never needs quoting in CSV or TSV.
        return "|".join(str(v) for v in value)
    return str(value)


def to_jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """A people row in JSON's type system, keeping lists and booleans as themselves."""
    out: dict[str, Any] = {}
    for key in PEOPLE_COLUMNS:
        value = row[key]
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, dt.datetime):
            out[key] = value.isoformat().replace("+00:00", "Z")
        elif isinstance(value, dt.date):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


# --- csv and tsv -----------------------------------------------------------


def _delimited(
    rows: list[dict[str, Any]],
    delimiter: str,
    *,
    header: bool,
    quoted_newlines: bool,
) -> str:
    buffer = io.StringIO(newline="")
    writer = csv_module.writer(buffer, delimiter=delimiter, lineterminator="\n")
    if header:
        writer.writerow(PEOPLE_COLUMNS)
    for row in rows:
        values = []
        for column in PEOPLE_COLUMNS:
            text = _scalar(row[column])
            if quoted_newlines and column == "bio" and text:
                # A real embedded newline, so the reader has to honour RFC 4180 quoting.
                text = text.replace(" ", "\n", 1)
            values.append(text)
        writer.writerow(values)
    return buffer.getvalue()


@generator()
def csv_people(
    ctx: GeneratorContext,
    *,
    rows: int,
    delimiter: str = ",",
    header: bool = True,
    bom: bool = False,
    encoding: str = "utf-8",
    quoted_newlines: bool = False,
) -> bytes:
    """The people dataset as delimited text.

    ``delimiter`` covers the TSV and semicolon variants; ``quoted_newlines`` puts a real
    newline inside a quoted field, which is where naive splitters break.
    """
    text = _delimited(
        ctx.dataset("people", rows), delimiter, header=header, quoted_newlines=quoted_newlines
    )
    prefix = b"\xef\xbb\xbf" if bom and encoding == "utf-8" else b""
    return prefix + text.encode(encoding)


@generator(parallel_safe=False)
def csv_sized(ctx: GeneratorContext, *, size: int) -> bytes:
    """A CSV of people rows fitted to ``size`` bytes (docs/05 §6: n = rows)."""

    def make(row_count: int) -> bytes:
        return _delimited(
            ctx.dataset("people", row_count), ",", header=True, quoted_newlines=False
        ).encode("utf-8")

    _, payload = fit(size, APPROX_TOLERANCE, make, n0=max(1, size // 260), n_min=1, n_max=size)
    return payload


# --- json and ndjson -------------------------------------------------------


@generator()
def json_people(ctx: GeneratorContext, *, rows: int, indent: int | None = 2) -> bytes:
    """The people dataset as a JSON array of objects."""
    payload = [to_jsonable(row) for row in ctx.dataset("people", rows)]
    return (json.dumps(payload, indent=indent, ensure_ascii=False) + "\n").encode("utf-8")


@generator(parallel_safe=False)
def json_sized(ctx: GeneratorContext, *, size: int) -> bytes:
    """A JSON array of people rows fitted to ``size`` bytes."""

    def make(row_count: int) -> bytes:
        payload = [to_jsonable(row) for row in ctx.dataset("people", row_count)]
        return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    _, payload = fit(size, APPROX_TOLERANCE, make, n0=max(1, size // 700), n_min=1, n_max=size)
    return payload


@generator()
def json_all_types(ctx: GeneratorContext) -> bytes:
    """Every JSON scalar shape a parser has to get right.

    Written as literal text rather than through ``json.dumps`` because several of the
    interesting cases — negative zero, an exponent form, an integer beyond 2^53, a lone
    surrogate pair escape — do not survive a Python round trip in the form being tested.
    """
    rng = ctx.rng
    body = f"""{{
  "null": null,
  "true": true,
  "false": false,
  "zero": 0,
  "negative_zero": -0.0,
  "integer": 42,
  "negative_integer": -42,
  "big_integer": 9007199254740993,
  "beyond_int64": 9223372036854775808,
  "float": 3.141592653589793,
  "exponent": 1.5e308,
  "small_exponent": 5e-324,
  "string": {json.dumps(lorem.sentence(rng), ensure_ascii=False)},
  "empty_string": "",
  "unicode": "caf\\u00e9 na\\u00efve \\u03a9 \\u4e2d\\u6587",
  "surrogate_pair": "\\ud83d\\ude00",
  "escapes": "quote:\\" backslash:\\\\ slash:\\/ newline:\\n tab:\\t bell:\\u0007",
  "empty_object": {{}},
  "empty_array": [],
  "array_of_mixed": [1, "two", 3.0, null, true, [], {{}}],
  "nested": {{"a": {{"b": {{"c": [1, 2, 3]}}}}}}
}}
"""
    return body.encode("utf-8")


@generator()
def json_nested(ctx: GeneratorContext, *, depth: int) -> bytes:
    """An object nested ``depth`` levels deep, for recursion limits."""
    payload: Any = {"leaf": lorem.sentence(ctx.rng)}
    for level in range(depth - 1, 0, -1):
        payload = {f"level{level}": payload}
    return (json.dumps(payload, indent=None, ensure_ascii=False) + "\n").encode("utf-8")


@generator()
def ndjson_people(ctx: GeneratorContext, *, rows: int) -> bytes:
    """One JSON object per line — the shape stream processors expect."""
    lines = [
        json.dumps(to_jsonable(row), separators=(",", ":"), ensure_ascii=False)
        for row in ctx.dataset("people", rows)
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


# --- xml -------------------------------------------------------------------


@generator()
def xml_people(ctx: GeneratorContext, *, rows: int) -> bytes:
    """The people dataset as elements, one child per column."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<people>"]
    for row in ctx.dataset("people", rows):
        out.append(f'  <person id="{row["id"]}">')
        for column in PEOPLE_COLUMNS:
            if column == "id":
                continue
            out.append(f"    <{column}>{escape(_scalar(row[column]))}</{column}>")
        out.append("  </person>")
    out.append("</people>")
    return ("\n".join(out) + "\n").encode("utf-8")


@generator()
def xml_namespaces(ctx: GeneratorContext) -> bytes:
    """Default and prefixed namespaces, plus an attribute in a namespace."""
    rng = ctx.rng
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<catalogue xmlns="https://loremfile.dev/ns/catalogue"
           xmlns:dc="http://purl.org/dc/elements/1.1/"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xsi:schemaLocation="https://loremfile.dev/ns/catalogue catalogue.xsd">
  <dc:title>{escape(lorem.sentence(rng, 3, 6))}</dc:title>
  <dc:creator>loremfile.dev</dc:creator>
  <items>
    <item id="1" dc:identifier={quoteattr("lf-0001")}>
      <name>{escape(" ".join(lorem.words(rng, 2)).title())}</name>
      <note xml:lang="en">{escape(lorem.sentence(rng))}</note>
    </item>
    <item id="2" dc:identifier={quoteattr("lf-0002")}>
      <name>{escape(" ".join(lorem.words(rng, 2)).title())}</name>
      <note xml:lang="de">{escape(lorem.sentence(rng))}</note>
    </item>
  </items>
</catalogue>
"""
    return body.encode("utf-8")


@generator()
def xml_rss2(ctx: GeneratorContext, *, items: int = 10) -> bytes:
    """An RSS 2.0 feed with fixed publication dates."""
    rng = ctx.rng
    published = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    entries = []
    for index in range(items):
        stamp = (published + dt.timedelta(days=index)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        entries.append(
            "    <item>\n"
            f"      <title>{escape(lorem.sentence(rng, 3, 7))}</title>\n"
            f"      <link>https://loremfile.dev/example/{index + 1}</link>\n"
            f'      <guid isPermaLink="false">lf-item-{index + 1:04d}</guid>\n'
            f"      <pubDate>{stamp}</pubDate>\n"
            f"      <description>{escape(lorem.sentence(rng))}</description>\n"
            "    </item>"
        )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "  <channel>\n"
        "    <title>loremfile.dev sample feed</title>\n"
        "    <link>https://loremfile.dev/</link>\n"
        f"    <description>{escape(lorem.sentence(rng))}</description>\n"
        "    <language>en-gb</language>\n"
        f"    <lastBuildDate>{published.strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>\n"
        + "\n".join(entries)
        + "\n  </channel>\n</rss>\n"
    )
    return body.encode("utf-8")


# --- yaml, toml, sql -------------------------------------------------------


@generator()
def yaml_config(ctx: GeneratorContext) -> bytes:
    """Anchors, aliases, multiple documents, block scalars and dates.

    Hand-written rather than dumped, because anchors and aliases are exactly what a
    round trip through PyYAML would throw away.
    """
    rng = ctx.rng
    body = f"""---
# loremfile.dev sample configuration
defaults: &defaults
  adapter: postgres
  encoding: utf8
  pool: 10
  timeout: 5.5

development:
  <<: *defaults
  database: loremfile_dev
  host: 127.0.0.1

production:
  <<: *defaults
  database: loremfile_prod
  host: db.example.com
  pool: 25

types:
  null_value: null
  tilde_null: ~
  bool_true: true
  bool_false: false
  integer: 42
  octal: 0o755
  hexadecimal: 0xFF
  float: 3.14159
  infinity: .inf
  not_a_number: .nan
  date: 2020-01-01
  timestamp: 2020-01-01T00:00:00Z
  quoted_string: "{escape(lorem.sentence(rng, 3, 5))}"
  single_quoted: 'it''s quoted'
  unicode: "café naïve Ω 中文"

block_literal: |
  This keeps its line breaks.
  Second line, indented below.
    Third line, further indented.

block_folded: >
  This is folded into a single line
  when the parser reads it, because
  the greater-than marker says so.

sequences:
  - plain
  - {{inline: mapping}}
  - [inline, sequence]
  -
    nested: mapping
---
# A second document in the same stream.
document: 2
note: {escape(lorem.sentence(rng, 4, 8))}
"""
    return body.encode("utf-8")


@generator()
def toml_config(ctx: GeneratorContext) -> bytes:
    """A TOML config covering the types a parser has to distinguish."""
    rng = ctx.rng
    body = f'''# loremfile.dev sample configuration
title = "loremfile sample"

[owner]
name = "loremfile.dev"
joined = 2020-01-01T00:00:00Z

[server]
host = "127.0.0.1"
port = 8080
enabled = true
ratio = 0.75
max_bytes = 100_000_000
banner = """
A multi-line basic string
that keeps its newline."""
literal = 'C:\\Users\\no\\escape'

[server.limits]
requests_per_second = 30
burst = 300

[[endpoints]]
path = "/manifest.json"
methods = ["GET", "HEAD"]

[[endpoints]]
path = "/sha256sums.txt"
methods = ["GET", "HEAD"]

[dates]
offset_datetime = 2020-01-01T00:00:00-05:00
local_datetime = 2020-01-01T00:00:00
local_date = 2020-01-01
local_time = 07:32:00

[notes]
text = "{escape(lorem.sentence(rng, 4, 8))}"
unicode = "café naïve Ω"
'''
    return body.encode("utf-8")


@generator()
def sql_inserts(ctx: GeneratorContext, *, rows: int) -> bytes:
    """Portable CREATE TABLE plus INSERT statements — no vendor-specific syntax."""

    def quote(value: object) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, int | Decimal):
            return str(value)
        return "'" + _scalar(value).replace("'", "''") + "'"

    out = [
        "-- loremfile.dev sample data. Portable SQL: no vendor-specific syntax.",
        "CREATE TABLE people (",
        "  id            INTEGER PRIMARY KEY,",
        "  first_name    VARCHAR(64) NOT NULL,",
        "  last_name     VARCHAR(64) NOT NULL,",
        "  email         VARCHAR(160) NOT NULL,",
        "  phone         VARCHAR(32),",
        "  street        VARCHAR(160),",
        "  city          VARCHAR(80),",
        "  country       CHAR(2),",
        "  birth_date    DATE,",
        "  signup_at     TIMESTAMP,",
        "  balance       DECIMAL(12,2),",
        "  is_active     SMALLINT,",
        "  tags          VARCHAR(120),",
        "  bio           VARCHAR(255)",
        ");",
        "",
    ]
    columns = ", ".join(PEOPLE_COLUMNS)
    for row in ctx.dataset("people", rows):
        values = ", ".join(quote(row[column]) for column in PEOPLE_COLUMNS)
        # S608: this writes a .sql *fixture file*; nothing executes it, and every
        # value went through quote() above. There is no query being built here.
        out.append(f"INSERT INTO people ({columns}) VALUES ({values});")  # noqa: S608
    return ("\n".join(out) + "\n").encode("utf-8")
