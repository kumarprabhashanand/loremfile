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
        "column_types": [str(field.type) for field in table.schema],
    }


@register("arrow")
def validate_arrow(data: bytes, _fixture: Fixture, mime: str) -> dict[str, Any]:
    """Arrow IPC in either format, told apart by the bytes and held to the served type.

    The file format starts and ends with `ARROW1`; the stream format has neither. A reader
    pointed at the wrong one fails, so a file served as a stream (or the reverse) is wrong
    even if every row is right.
    """
    ipc_format = "file" if data[:6] == ARROW_MAGIC and data[-6:] == ARROW_MAGIC else "stream"
    if mime.partition(";")[0].strip() != ARROW_TYPES[ipc_format]:
        raise ValidationError(f"is the IPC {ipc_format} format but is served as {mime}")
    try:
        if ipc_format == "file":
            with pyarrow.ipc.open_file(pyarrow.BufferReader(data)) as reader:
                table = reader.read_all()
                batches = reader.num_record_batches
        else:
            with pyarrow.ipc.open_stream(pyarrow.BufferReader(data)) as reader:
                parts = list(reader)
                table = pyarrow.Table.from_batches(parts, schema=reader.schema)
                batches = len(parts)
    except Exception as exc:
        raise ValidationError(f"pyarrow could not read the IPC {ipc_format}: {exc}") from exc
    return {
        "rows": table.num_rows,
        "columns": table.num_columns,
        "row_groups": batches,
        "column_names": list(table.schema.names),
        "ipc_format": ipc_format,
        "compression": _ipc_compression(data, ipc_format),
        "column_types": [str(field.type) for field in table.schema],
        "null_counts": [column.null_count for column in table.columns],
    }


#: The file format's leading and trailing magic (the leading copy is padded to 8 bytes).
ARROW_MAGIC = b"ARROW1"
ARROW_TYPES = {
    "file": "application/vnd.apache.arrow.file",
    "stream": "application/vnd.apache.arrow.stream",
}
#: A compressed IPC buffer is its uncompressed length as an int64, then one codec frame.
#: pyarrow decompresses transparently and never says which codec it met, so the frame's
#: own magic is the measurement.
CODEC_MAGIC = {b"\x28\xb5\x2f\xfd": "zstd", b"\x04\x22\x4d\x18": "lz4"}
LENGTH_PREFIX_BYTES = 8


def _ipc_compression(data: bytes, ipc_format: str) -> str:
    """The codec of the first record batch's body, or `none`."""
    messages = data[8:] if ipc_format == "file" else data
    for message in pyarrow.ipc.MessageReader.open_stream(pyarrow.BufferReader(messages)):
        if message.type != "record batch" or message.body is None:
            continue
        head = bytes(message.body[LENGTH_PREFIX_BYTES : LENGTH_PREFIX_BYTES + 4])
        return CODEC_MAGIC.get(head, "none")
    return "none"


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
