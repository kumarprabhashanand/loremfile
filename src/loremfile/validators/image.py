"""Validators for raster images and SVG (docs/04 §1.3).

Every raster image is opened twice: once with ``verify()``, which checks the file is
structurally sound without decoding it, and then again to read the pixels — Pillow
requires a reopen after ``verify()``, and a file that survives only the first is exactly
the sort of half-broken image worth catching.
"""

from __future__ import annotations

import io
from typing import Any

from lxml import etree
from PIL import Image, ImageFile

from loremfile.catalog import Fixture
from loremfile.validators import ValidationError, register
from loremfile.validators.text import text_props

#: Refuse to decode a bomb: a fixture that needs more than this is a mistake, and
#: Pillow's own limit would otherwise only warn.
Image.MAX_IMAGE_PIXELS = 120_000_000

#: Fixtures are complete files; a truncated one must fail rather than be tolerated.
ImageFile.LOAD_TRUNCATED_IMAGES = False

RASTER_FORMATS = ("png", "jpg", "gif", "webp", "avif", "bmp", "tiff", "ico")

#: EXIF tag 0x0112.
ORIENTATION_TAG = 0x0112


def _raster_props(data: bytes) -> dict[str, Any]:
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
    except Exception as exc:
        raise ValidationError(f"Pillow could not verify it: {exc}") from exc

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            width, height = image.size
            mode = image.mode
            frames = getattr(image, "n_frames", 1)
            animated = bool(getattr(image, "is_animated", False))
            fmt = (image.format or "").lower()
            progressive = bool(image.info.get("progressive") or image.info.get("progression"))
            exif = image.getexif()
            orientation = exif.get(ORIENTATION_TAG) if exif else None
            sizes = sorted({s[0] for s in image.info["sizes"]}) if "sizes" in image.info else None
    except Exception as exc:
        raise ValidationError(f"Pillow could not decode it: {exc}") from exc

    props: dict[str, Any] = {
        "width": width,
        "height": height,
        "mode": mode,
        "frames": frames,
        "animated": animated,
        "format": fmt,
        "progressive": progressive,
    }
    if orientation is not None:
        props["exif_orientation"] = int(orientation)
    if sizes is not None:
        props["sizes"] = sizes
    return props


def _register_raster(fmt: str) -> None:
    @register(fmt)
    def _validate(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
        return _raster_props(data)


for _format in RASTER_FORMATS:
    _register_raster(_format)


@register("svg")
def validate_svg(data: bytes, _fixture: Fixture, mime: str) -> dict[str, Any]:
    """SVG is XML, so it is parsed as XML — and checked for the things policy forbids.

    ``validators/policy.py`` scans the bytes as well. This is the structural half: an
    SVG that parses but carries a script element or an external reference must fail
    here too, because a published SVG renders in a browser.
    """
    props = text_props(data, mime)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        root = etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ValidationError(f"is not well-formed XML: {exc}") from exc

    if etree.QName(root).localname != "svg":
        raise ValidationError(f"root element is {etree.QName(root).localname!r}, not 'svg'")

    for element in root.iter():
        local = etree.QName(element).localname.lower()
        if local in {"script", "foreignobject"}:
            raise ValidationError(f"contains a <{local}> element, which policy forbids")
        for name, value in element.attrib.items():
            attribute = etree.QName(name).localname.lower() if "}" in name else name.lower()
            if attribute.startswith("on"):
                raise ValidationError(f"has an event-handler attribute {attribute!r}")
            if isinstance(value, str) and value.strip().lower().startswith("javascript:"):
                raise ValidationError(f"{attribute!r} uses a javascript: URL")
            if attribute in {"href", "xlink:href"} and isinstance(value, str):
                target = value.strip().lower()
                if not target.startswith(("data:", "#")):
                    raise ValidationError(
                        f"references something external: {value[:60]!r}. "
                        "SVG fixtures must be self-contained."
                    )

    props.update(
        {
            "root_element": "svg",
            "width": root.get("width"),
            "height": root.get("height"),
            "viewbox": root.get("viewBox"),
            "has_dtd": False,
            "elements": sum(1 for _ in root.iter()),
        }
    )
    return props
