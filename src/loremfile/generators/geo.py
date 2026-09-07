"""Geographic fixtures — geojson, gpx, kml, kmz (docs/05 §3.7).

Coordinates are generated inside a fixed bounding box over open ocean south-west of
Africa, so no fixture names or implies a real place. Elevations and timestamps are
synthetic and monotonic, which is what a track parser actually needs to test against.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from xml.sax.saxutils import escape

from loremfile.generators.base import GeneratorContext, generator
from loremfile.util import lorem
from loremfile.util.zipnorm import normalize

#: A bounding box in the South Atlantic. Deliberately empty ocean: a synthetic fixture
#: should not put invented data on top of somewhere real.
BOUNDS = (-20.0, -35.0, -10.0, -25.0)  # west, south, east, north

TRACK_START = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)


def _coordinate(index: int, total: int) -> tuple[float, float]:
    """A point on a smooth path across the bounding box, rounded to 6 decimals."""
    west, south, east, north = BOUNDS
    fraction = index / max(total - 1, 1)
    longitude = west + (east - west) * fraction
    latitude = south + (north - south) * (0.5 + 0.4 * ((index * 7) % 11 - 5) / 5)
    return round(longitude, 6), round(latitude, 6)


@generator()
def geojson_points(ctx: GeneratorContext, *, count: int = 100) -> bytes:
    """A FeatureCollection of Point features, each with a few properties."""
    rng = ctx.rng
    features = []
    for index in range(count):
        longitude, latitude = _coordinate(index, count)
        features.append(
            {
                "type": "Feature",
                "id": index + 1,
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "properties": {
                    "name": " ".join(lorem.words(rng, 2)).title(),
                    "category": rng.choice(["buoy", "marker", "sample", "station"]),
                    "elevation_m": round(rng.uniform(-4000, 0), 1),
                    "recorded_at": (TRACK_START + dt.timedelta(hours=index))
                    .isoformat()
                    .replace("+00:00", "Z"),
                },
            }
        )
    document = {
        "type": "FeatureCollection",
        "bbox": list(BOUNDS),
        "features": features,
    }
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


@generator()
def gpx_track(ctx: GeneratorContext, *, points: int = 100) -> bytes:
    """A GPX 1.1 track with one segment, timestamps and elevations."""
    rng = ctx.rng
    trkpts = []
    for index in range(points):
        longitude, latitude = _coordinate(index, points)
        stamp = (TRACK_START + dt.timedelta(seconds=index * 30)).isoformat().replace("+00:00", "Z")
        trkpts.append(
            f'      <trkpt lat="{latitude}" lon="{longitude}">\n'
            f"        <ele>{round(rng.uniform(0, 120), 1)}</ele>\n"
            f"        <time>{stamp}</time>\n"
            "      </trkpt>"
        )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="loremfile.dev"\n'
        '     xmlns="http://www.topografix.com/GPX/1/1"\n'
        '     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        '     xsi:schemaLocation="http://www.topografix.com/GPX/1/1 '
        'http://www.topografix.com/GPX/1/1/gpx.xsd">\n'
        "  <metadata>\n"
        "    <name>loremfile.dev sample track</name>\n"
        f"    <time>{TRACK_START.isoformat().replace('+00:00', 'Z')}</time>\n"
        "  </metadata>\n"
        "  <trk>\n"
        f"    <name>{escape(' '.join(lorem.words(rng, 3)).title())}</name>\n"
        "    <trkseg>\n" + "\n".join(trkpts) + "\n    </trkseg>\n"
        "  </trk>\n</gpx>\n"
    )
    return body.encode("utf-8")


def _kml_document(ctx: GeneratorContext, count: int) -> str:
    rng = ctx.rng
    placemarks = []
    for index in range(count):
        longitude, latitude = _coordinate(index, count)
        placemarks.append(
            "    <Placemark>\n"
            f"      <name>{escape(' '.join(lorem.words(rng, 2)).title())}</name>\n"
            f"      <description>{escape(lorem.sentence(rng, 5, 10))}</description>\n"
            f"      <Point><coordinates>{longitude},{latitude},0</coordinates></Point>\n"
            "    </Placemark>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        "  <Document>\n"
        "    <name>loremfile.dev sample placemarks</name>\n"
        "    <open>1</open>\n" + "\n".join(placemarks) + "\n  </Document>\n</kml>\n"
    )


@generator()
def kml_placemarks(ctx: GeneratorContext, *, count: int = 10) -> bytes:
    """A KML document of Point placemarks."""
    return _kml_document(ctx, count).encode("utf-8")


@generator()
def kmz_placemarks(ctx: GeneratorContext, *, count: int = 10) -> bytes:
    """The same KML, zipped as KMZ — `doc.kml` first, per the KMZ convention.

    Normalised through `zipnorm` like every other zip-based fixture, so the archive is
    byte-identical between builds.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", _kml_document(ctx, count))
    return normalize(buffer.getvalue())
