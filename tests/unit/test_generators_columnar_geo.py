"""M3.2b: parquet, arrow, avro, sqlite, geojson, gpx, kml, kmz.

Determinism gets the most attention here. These are the formats where writers embed
metadata of their own — a version string, a sync marker, a database header — and where
docs/06 §4's warning applies: an assumption about a library's internals is only ever
proved by running it twice.
"""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import fastavro
import pyarrow.parquet
import pytest

from loremfile.build import load_generators
from loremfile.catalog import Catalog, Fixture
from loremfile.generators import columnar
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import _REGISTRY, ValidationError, load, validate
from loremfile.validators.geo import _check_position

WORKDIR = Path(tempfile.gettempdir())
CATALOG = Catalog.load()
load_generators()
load()


def ctx(path: str) -> GeneratorContext:
    return GeneratorContext(path=path, workdir=WORKDIR)


def fixture(path: str) -> Fixture:
    return CATALOG.by_path[path]


def build(path: str) -> bytes:
    entry = fixture(path)
    context = ctx(path)
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **entry.params)
    assert isinstance(out, bytes)
    return out


def check(path: str) -> dict:
    """Full validation of the real fixture, including the catalog's `expect` counts."""
    entry = fixture(path)
    report = validate(build(path), entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures
    return report.props


def measure(path: str, payload: bytes) -> dict:
    """Structural validation only, for reduced-size payloads.

    The catalog's `expect` block states the real fixture's counts, so comparing a
    20-row stand-in against it would fail for the wrong reason. This runs the format's
    own validator, which still raises on anything structurally wrong.
    """
    entry = fixture(path)
    return _REGISTRY[entry.format](payload, entry, CATALOG.mime_for(entry))


SMALL = {
    "parquet/people-1000.parquet": {"rows": 50},
    "arrow/people-1000.arrow": {"rows": 50},
    "avro/people-1000.avro": {"rows": 50},
    "sqlite/people-1000.sqlite": {"rows": 50},
    "sqlite/multi-table-with-fk-indexes-views.sqlite": {"people": 20, "orders": 40},
    "geojson/points-100.geojson": {"count": 20},
    "gpx/track-100-points.gpx": {"points": 20},
    "kml/placemarks-10.kml": {"count": 5},
    "kmz/placemarks-10.kmz": {"count": 5},
}


def build_small(path: str) -> bytes:
    """Generate with reduced parameters — the determinism property is size-independent."""
    entry = fixture(path)
    context = ctx(path)
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **SMALL[path])
    assert isinstance(out, bytes)
    return out


# --- determinism, the reason this milestone was risky ----------------------


@pytest.mark.parametrize("path", sorted(SMALL))
def test_running_twice_gives_identical_bytes(path: str) -> None:
    assert build_small(path) == build_small(path)


def test_avro_sync_marker_is_explicit_and_seed_derived() -> None:
    """docs/06 §4 assumed the patched `random` covered this. It does not.

    fastavro._write is a compiled C extension, so it draws randomness below the Python
    layer where the determinism guard cannot reach. The marker is therefore passed in
    explicitly, derived from the fixture's own seed — which also means two different
    fixtures get two different markers.
    """
    first = build_small("avro/people-1000.avro")
    marker = first[-16:]
    assert fastavro.reader(io.BytesIO(first))  # still a readable Avro file
    assert marker == build_small("avro/people-1000.avro")[-16:]

    other = ctx("avro/other.avro")
    with deterministic(other.seed):
        different = columnar.avro_people(other, rows=50)
    assert different[-16:] != marker, "two fixtures must not share a sync marker"


def test_sqlite_files_are_vacuumed_and_page_sized() -> None:
    props = measure("sqlite/people-1000.sqlite", build_small("sqlite/people-1000.sqlite"))
    assert props["page_size"] == 4096
    assert props["journal_mode"] == "delete"


# --- columnar contents -----------------------------------------------------


def test_parquet_round_trips_with_the_expected_schema() -> None:
    payload = build_small("parquet/people-1000.parquet")
    table = pyarrow.parquet.read_table(io.BytesIO(payload))
    assert table.num_rows == 50
    assert table.column_names[:4] == ["id", "first_name", "last_name", "email"]
    assert table.column("id").to_pylist()[:3] == [1, 2, 3]


def test_parquet_has_magic_at_both_ends() -> None:
    payload = build_small("parquet/people-1000.parquet")
    assert payload.startswith(b"PAR1") and payload.endswith(b"PAR1")


def test_arrow_is_the_file_format_not_the_stream_format() -> None:
    payload = build_small("arrow/people-1000.arrow")
    assert payload.startswith(b"ARROW1")
    with pyarrow.ipc.open_file(pyarrow.BufferReader(payload)) as reader:
        assert reader.read_all().num_rows == 50


def test_avro_carries_its_schema() -> None:
    reader = fastavro.reader(io.BytesIO(build_small("avro/people-1000.avro")))
    assert reader.writer_schema["name"] == "dev.loremfile.Person"
    records = list(reader)
    assert len(records) == 50
    assert records[0]["id"] == 1


def test_every_columnar_format_holds_the_same_first_person() -> None:
    """The point of having four of them: the same row, four encodings."""
    parquet_row = pyarrow.parquet.read_table(
        io.BytesIO(build_small("parquet/people-1000.parquet"))
    ).to_pylist()[0]
    with pyarrow.ipc.open_file(
        pyarrow.BufferReader(build_small("arrow/people-1000.arrow"))
    ) as reader:
        arrow_row = reader.read_all().to_pylist()[0]
    avro_row = next(iter(fastavro.reader(io.BytesIO(build_small("avro/people-1000.avro")))))
    for field in ("id", "first_name", "last_name", "email", "city", "country"):
        assert parquet_row[field] == arrow_row[field] == avro_row[field]


# --- sqlite ----------------------------------------------------------------


def test_multi_table_has_the_relations_it_claims() -> None:
    payload = build_small("sqlite/multi-table-with-fk-indexes-views.sqlite")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "db.sqlite"
        path.write_bytes(payload)
        connection = sqlite3.connect(path)
        try:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            assert names == {"people", "orders", "products", "audit"}
            # The view must actually resolve.
            totals = connection.execute(
                "SELECT person_id, order_count FROM order_totals LIMIT 3"
            ).fetchall()
            assert len(totals) == 3
        finally:
            connection.close()


def test_multi_table_foreign_keys_all_resolve() -> None:
    """Every orders.person_id must exist in people, or the fixture is a broken example."""
    payload = build_small("sqlite/multi-table-with-fk-indexes-views.sqlite")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "db.sqlite"
        path.write_bytes(payload)
        connection = sqlite3.connect(path)
        try:
            orphans = connection.execute(
                "SELECT COUNT(*) FROM orders o "
                "LEFT JOIN people p ON p.id = o.person_id WHERE p.id IS NULL"
            ).fetchone()[0]
            assert orphans == 0
        finally:
            connection.close()


# --- geo -------------------------------------------------------------------


def test_geojson_is_a_feature_collection_with_valid_positions() -> None:
    props = measure("geojson/points-100.geojson", build_small("geojson/points-100.geojson"))
    assert props["geometry_types"] == ["Point"]
    document = json.loads(build_small("geojson/points-100.geojson"))
    assert document["type"] == "FeatureCollection"
    for feature in document["features"]:
        longitude, latitude = feature["geometry"]["coordinates"]
        assert -180 <= longitude <= 180
        assert -90 <= latitude <= 90


def test_position_check_catches_swapped_coordinates() -> None:
    """A latitude of 190 is impossible; swapping is the classic GeoJSON mistake."""
    _check_position([10.0, 45.0], "ok")
    with pytest.raises(ValidationError, match="swapped"):
        _check_position([10.0, 190.0], "bad")


def test_position_check_rejects_a_single_number() -> None:
    with pytest.raises(ValidationError, match="at least longitude and latitude"):
        _check_position([10.0], "bad")


def test_gpx_track_has_points_with_time_and_elevation() -> None:
    payload = build_small("gpx/track-100-points.gpx")
    text = payload.decode()
    assert text.count("<trkpt") == 20
    assert "<ele>" in text and "<time>" in text
    assert measure("gpx/track-100-points.gpx", payload)["tracks"] == 1


def test_kmz_puts_doc_kml_first_and_the_kml_inside_is_valid() -> None:
    payload = build_small("kmz/placemarks-10.kmz")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == ["doc.kml"]
        assert archive.testzip() is None
    assert measure("kmz/placemarks-10.kmz", payload)["placemarks"] == 5


def test_kmz_is_normalised_like_every_other_zip() -> None:
    """Two builds must be byte-identical, which zip timestamps would otherwise prevent."""
    assert build_small("kmz/placemarks-10.kmz") == build_small("kmz/placemarks-10.kmz")


# --- negative tests --------------------------------------------------------


def test_truncated_parquet_is_rejected() -> None:
    entry = fixture("parquet/people-1000.parquet")
    payload = build_small("parquet/people-1000.parquet")[:-64]
    report = validate(payload, entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("PAR1" in f or "could not read" in f for f in report.failures)


def test_corrupt_sqlite_is_rejected() -> None:
    entry = fixture("sqlite/people-1000.sqlite")
    payload = bytearray(build_small("sqlite/people-1000.sqlite"))
    payload[5000:5400] = b"\xff" * 400
    report = validate(bytes(payload), entry, CATALOG.mime_for(entry))
    assert not report.ok


def test_avro_with_a_damaged_body_is_rejected() -> None:
    entry = fixture("avro/people-1000.avro")
    payload = bytearray(build_small("avro/people-1000.avro"))
    payload[-200:] = b"\x00" * 200
    report = validate(bytes(payload), entry, CATALOG.mime_for(entry))
    assert not report.ok


def test_geojson_that_is_not_a_feature_collection_is_rejected() -> None:
    entry = fixture("geojson/points-100.geojson")
    report = validate(b'{"type": "Point", "coordinates": [0, 0]}\n', entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("FeatureCollection" in f for f in report.failures)


def test_kmz_without_doc_kml_first_is_rejected() -> None:
    entry = fixture("kmz/placemarks-10.kmz")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("something-else.kml", "<kml/>")
    report = validate(buffer.getvalue(), entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("doc.kml" in f for f in report.failures)


def test_malformed_gpx_is_rejected() -> None:
    entry = fixture("gpx/track-100-points.gpx")
    report = validate(b"<gpx><trk></gpx>\n", entry, CATALOG.mime_for(entry))
    assert not report.ok
