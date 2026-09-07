"""Validators for the columnar and database formats (docs/04 §1.3).

Each opens the file with the library that would read it in anger, so a fixture that
parses here is one a user's pipeline can actually consume.
"""

from __future__ import annotations

import io
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import fastavro
import pyarrow
import pyarrow.parquet

from loremfile.catalog import Fixture
from loremfile.validators import ValidationError, register

#: Parquet is the one format that must be checked at both ends: the trailing magic is
#: what proves the footer was written, and a truncated file keeps the header.
PARQUET_MAGIC = b"PAR1"


@register("parquet")
def validate_parquet(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
    if not data.endswith(PARQUET_MAGIC):
        raise ValidationError("does not end with PAR1; the footer is missing or truncated")
    try:
        metadata = pyarrow.parquet.read_metadata(io.BytesIO(data))
        table = pyarrow.parquet.read_table(io.BytesIO(data))
    except Exception as exc:
        raise ValidationError(f"pyarrow could not read it: {exc}") from exc
    compressions = {
        metadata.row_group(g).column(c).compression
        for g in range(metadata.num_row_groups)
        for c in range(metadata.num_columns)
    }
    return {
        "rows": metadata.num_rows,
        "columns": metadata.num_columns,
        "row_groups": metadata.num_row_groups,
        "compression": sorted(compressions)[0].lower() if compressions else "none",
        "column_names": list(table.schema.names),
    }


@register("arrow")
def validate_arrow(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
    try:
        with pyarrow.ipc.open_file(pyarrow.BufferReader(data)) as reader:
            table = reader.read_all()
            batches = reader.num_record_batches
    except Exception as exc:
        raise ValidationError(f"pyarrow could not read the IPC file: {exc}") from exc
    return {
        "rows": table.num_rows,
        "columns": table.num_columns,
        "row_groups": batches,
        "column_names": list(table.schema.names),
    }


@register("avro")
def validate_avro(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
    try:
        reader = fastavro.reader(io.BytesIO(data))
        schema = reader.writer_schema
        records = list(reader)
    except Exception as exc:
        raise ValidationError(f"fastavro could not read it: {exc}") from exc
    # An Avro schema may be a record (a dict), a union (a list) or a bare type name.
    # Only a record has named fields, which is what these fixtures are.
    if not isinstance(schema, dict):
        raise ValidationError(f"writer schema is a {type(schema).__name__}, expected a record")
    fields = [field["name"] for field in schema.get("fields", [])]
    return {
        "rows": len(records),
        "columns": len(fields),
        "compression": reader.codec,
        "column_names": fields,
    }


@register("sqlite")
def validate_sqlite(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
    """Open the database and run an integrity check, not just a magic-byte test."""
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "check.sqlite"
        path.write_bytes(data)
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValidationError(f"PRAGMA integrity_check said {integrity!r}")
            tables = [
                name
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            rows_total = 0
            for table in tables:
                # Identifiers cannot be bound; they come from sqlite_master, not input.
                count = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()  # noqa: S608
                rows_total += count[0]
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            views = [
                name
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
                )
            ]
            indexes = [
                name
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            triggers = [
                name
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name"
                )
            ]
            has_fts = any("fts" in t.lower() for t in tables)
        finally:
            connection.close()
    return {
        "tables": len(tables),
        "table_names": tables,
        "rows_total": rows_total,
        "page_size": page_size,
        "journal_mode": journal_mode,
        "has_fts": has_fts,
        "views": len(views),
        "indexes": len(indexes),
        "triggers": len(triggers),
    }
