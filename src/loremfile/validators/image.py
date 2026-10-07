"""Validators for raster images and SVG (docs/04 §1.3).

Every raster image is opened twice: once with ``verify()``, which checks the file is
structurally sound without decoding it, and then again to read the pixels — Pillow
requires a reopen after ``verify()``, and a file that survives only the first is exactly
the sort of half-broken image worth catching.
"""

from __future__ import annotations

import io
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from lxml import etree
from PIL import Image, ImageFile

from loremfile.catalog import Fixture
from loremfile.util.ffmpeg import FfmpegError, tool
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


# --- heic ------------------------------------------------------------------
#
# Pillow cannot read HEIC, so two readers that share nothing with the encoder do: the box
# walk below reads the container, and heif-convert (libheif with libde265, not x265)
# decodes the picture. The decoded size must equal the size the container declares.

#: An ISO-BMFF box header: a 32-bit size and a four-character type.
BOX_HEADER = 8

#: `infe` versions from 2 carry an item type; version 2 numbers items in 16 bits, later
#: versions in 32.
INFE_TYPED = 2


def _boxes(data: bytes, start: int, end: int) -> Iterator[tuple[str, int, int]]:
    """(type, payload start, box end) for each ISO-BMFF box in ``data[start:end]``."""
    offset = start
    while offset < end:
        if end - offset < BOX_HEADER:
            raise ValidationError(f"a box header at byte {offset} is cut short")
        size = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8].decode("latin-1")
        header = BOX_HEADER
        if size == 1:
            size, header = int.from_bytes(data[offset + 8 : offset + 16], "big"), 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            raise ValidationError(f"box {kind!r} at byte {offset} runs past its parent")
        yield kind, offset + header, offset + size
        offset += size


def _children(data: bytes, start: int, end: int) -> dict[str, tuple[int, int]]:
    return {kind: (s, e) for kind, s, e in _boxes(data, start, end)}


def _uint(data: bytes, offset: int, size: int) -> int:
    return int.from_bytes(data[offset : offset + size], "big")


def _heif_container(data: bytes) -> dict[str, Any]:
    """Brands, the primary item's type and its declared size, from the boxes alone."""
    top = list(_boxes(data, 0, len(data)))
    if not top or top[0][0] != "ftyp":
        raise ValidationError("does not start with an ftyp box")
    _, start, end = top[0]
    major = data[start : start + 4].decode("latin-1")
    brands = [data[i : i + 4].decode("latin-1") for i in range(start + 8, end, 4)]
    boxes = {kind: (s, e) for kind, s, e in top}
    if "meta" not in boxes or "mdat" not in boxes:
        raise ValidationError(f"has no {'meta' if 'meta' not in boxes else 'mdat'} box")

    meta = _children(data, boxes["meta"][0] + 4, boxes["meta"][1])  # meta is a FullBox
    for needed in ("pitm", "iinf", "iprp"):
        if needed not in meta:
            raise ValidationError(f"its meta box has no {needed}")
    pitm = meta["pitm"][0]
    primary = _uint(data, pitm + 4, 2 if data[pitm] == 0 else 4)

    iinf = meta["iinf"][0]
    skip = 4 + (2 if data[iinf] == 0 else 4)
    types: dict[int, str] = {}
    for kind, s, _ in _boxes(data, iinf + skip, meta["iinf"][1]):
        if kind != "infe" or data[s] < INFE_TYPED:
            continue
        width = 2 if data[s] == INFE_TYPED else 4
        item = _uint(data, s + 4, width)
        types[item] = data[s + 4 + width + 2 : s + 4 + width + 6].decode("latin-1")
    if primary not in types:
        raise ValidationError(f"the primary item {primary} has no infe entry")

    iprp = _children(data, *meta["iprp"])
    if "ipco" not in iprp or "ipma" not in iprp:
        raise ValidationError("its iprp box lacks ipco or ipma")
    properties = list(_boxes(data, *iprp["ipco"]))
    ipma = iprp["ipma"][0]
    version, flags = data[ipma], _uint(data, ipma + 1, 3)
    cursor = ipma + 8
    associated: list[int] = []
    for _ in range(_uint(data, ipma + 4, 4)):
        item_size = 2 if version < 1 else 4
        item = _uint(data, cursor, item_size)
        cursor += item_size
        count = data[cursor]
        cursor += 1
        index_size = 2 if flags & 1 else 1
        mask = 0x7FFF if flags & 1 else 0x7F
        indices = [_uint(data, cursor + i * index_size, index_size) & mask for i in range(count)]
        cursor += count * index_size
        if item == primary:
            associated = indices
    extents = [properties[i - 1] for i in associated if 0 < i <= len(properties)]
    ispe = [s for kind, s, _ in extents if kind == "ispe"]
    if len(ispe) != 1:
        raise ValidationError(f"the primary item has {len(ispe)} ispe properties, not one")
    return {
        "major_brand": major,
        "compatible_brands": ",".join(brands),
        "primary_item_type": types[primary],
        "items": len(types),
        "width": _uint(data, ispe[0] + 4, 4),
        "height": _uint(data, ispe[0] + 8, 4),
    }


def _heif_decode(data: bytes) -> Image.Image:
    try:
        convert = tool("heif-convert")
    except FfmpegError as exc:
        raise ValidationError(str(exc)) from exc
    with tempfile.TemporaryDirectory() as temporary:
        source, target = Path(temporary) / "in.heic", Path(temporary) / "out.png"
        source.write_bytes(data)
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [convert, str(source), str(target)], capture_output=True, timeout=120, check=False
        )
        if completed.returncode != 0 or not target.is_file():
            tail = (completed.stdout + completed.stderr).decode("utf-8", "replace").strip()
            raise ValidationError(f"heif-convert could not decode it: {tail[-300:]}")
        with Image.open(target) as image:
            image.load()
            return image.copy()


@register("heic")
def validate_heic(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
    try:
        props = _heif_container(data)
    except IndexError as exc:
        raise ValidationError(f"its boxes end before their contents do: {exc}") from exc
    if props["major_brand"] != "heic" or props["primary_item_type"] != "hvc1":
        raise ValidationError(
            f"is brand {props['major_brand']!r} with a {props['primary_item_type']!r} "
            "primary item, not an HEVC-coded HEIC"
        )
    decoded = _heif_decode(data)
    if decoded.size != (props["width"], props["height"]):
        raise ValidationError(
            f"decodes to {decoded.size[0]}x{decoded.size[1]}, but its ispe declares "
            f"{props['width']}x{props['height']}"
        )
    return {**props, "mode": decoded.mode, "format": "heic"}


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
