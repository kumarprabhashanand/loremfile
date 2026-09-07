"""Validators for the geographic formats (docs/04 §1.3).

GeoJSON is validated as JSON *and* as geometry: a file that parses but whose coordinates
are the wrong way round is worse than one that fails outright, because it looks fine.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from lxml import etree

from loremfile.catalog import Fixture
from loremfile.validators import ValidationError, register
from loremfile.validators.text import text_props

#: Longitude then latitude, in that order, is the whole of GeoJSON's coordinate rule
#: (RFC 7946 §3.1.1) and the single most common thing to get wrong.
LONGITUDE_RANGE = (-180.0, 180.0)
LATITUDE_RANGE = (-90.0, 90.0)

#: A GeoJSON position is [longitude, latitude] with an optional altitude.
MIN_POSITION_VALUES = 2


def _check_position(position: list[Any], where: str) -> None:
    if len(position) < MIN_POSITION_VALUES:
        raise ValidationError(f"{where}: a position needs at least longitude and latitude")
    longitude, latitude = position[0], position[1]
    if not LONGITUDE_RANGE[0] <= longitude <= LONGITUDE_RANGE[1]:
        raise ValidationError(f"{where}: longitude {longitude} is out of range")
    if not LATITUDE_RANGE[0] <= latitude <= LATITUDE_RANGE[1]:
        raise ValidationError(f"{where}: latitude {latitude} is out of range — are they swapped?")


@register("geojson")
def validate_geojson(data: bytes, _fixture: Fixture, mime: str) -> dict[str, Any]:
    props = text_props(data, mime)
    try:
        document = json.loads(data.decode(props["encoding"]))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"is not valid JSON: {exc}") from exc
    if document.get("type") != "FeatureCollection":
        raise ValidationError(f"top-level type is {document.get('type')!r}, not FeatureCollection")
    features = document.get("features", [])
    geometry_types = set()
    for index, feature in enumerate(features):
        geometry = feature.get("geometry") or {}
        geometry_types.add(geometry.get("type"))
        if geometry.get("type") == "Point":
            _check_position(geometry.get("coordinates", []), f"feature {index}")
    props.update(
        {
            "top_type": "object",
            "items": len(features),
            "features": len(features),
            "geometry_types": sorted(t for t in geometry_types if t),
        }
    )
    return props


def _xml_root(data: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        return etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ValidationError(f"is not well-formed XML: {exc}") from exc


@register("gpx")
def validate_gpx(data: bytes, _fixture: Fixture, mime: str) -> dict[str, Any]:
    props = text_props(data, mime)
    root = _xml_root(data)
    namespace = {"gpx": "http://www.topografix.com/GPX/1/1"}
    points = root.findall(".//gpx:trkpt", namespace)
    for index, point in enumerate(points):
        _check_position([float(point.get("lon")), float(point.get("lat"))], f"trkpt {index}")
    props.update(
        {
            "root_element": etree.QName(root).localname,
            "has_dtd": False,
            "namespaces": sorted({u for u in root.nsmap.values() if u}),
            "track_points": len(points),
            "tracks": len(root.findall(".//gpx:trk", namespace)),
        }
    )
    return props


@register("kml")
def validate_kml(data: bytes, _fixture: Fixture, mime: str) -> dict[str, Any]:
    props = text_props(data, mime)
    root = _xml_root(data)
    namespace = {"kml": "http://www.opengis.net/kml/2.2"}
    placemarks = root.findall(".//kml:Placemark", namespace)
    for index, placemark in enumerate(placemarks):
        coordinates = placemark.find(".//kml:coordinates", namespace)
        if coordinates is None or not coordinates.text:
            continue
        parts = [float(v) for v in coordinates.text.strip().split(",")]
        _check_position(parts, f"placemark {index}")
    props.update(
        {
            "root_element": etree.QName(root).localname,
            "has_dtd": False,
            "namespaces": sorted({u for u in root.nsmap.values() if u}),
            "placemarks": len(placemarks),
        }
    )
    return props


@register("kmz")
def validate_kmz(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    """A KMZ is a zip whose first entry is `doc.kml`; the KML inside is validated too."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"is not a valid zip: {exc}") from exc
    with archive:
        if archive.testzip() is not None:
            raise ValidationError("zip contains a corrupt entry")
        names = archive.namelist()
        if not names or names[0] != "doc.kml":
            raise ValidationError(f"first entry is {names[:1]}, expected ['doc.kml']")
        inner = archive.read("doc.kml")
        infos = archive.infolist()
    # The KML inside has to be valid on its own terms.
    kml_props = validate_kml(inner, fixture, "application/vnd.google-earth.kml+xml")
    return {
        "entries": len(names),
        "directories": sum(1 for n in names if n.endswith("/")),
        "method": "deflate" if infos[0].compress_type == zipfile.ZIP_DEFLATED else "stored",
        "encrypted": False,
        "zip64": False,
        "comment": archive.comment.decode("utf-8", "replace") if archive.comment else "",
        "placemarks": kml_props["placemarks"],
    }
