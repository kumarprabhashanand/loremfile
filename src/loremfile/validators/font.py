"""Validators for the font family (docs/06 §6).

A font is read back with fontTools and described by what it contains: outlines in the
expected flavour, a character map covering printable ASCII, and the metrics a renderer
needs. The timestamps are checked too — `head.created` and `head.modified` are the two
fields a font library fills from the clock, and a fixture whose hash moves every build is
not a fixture.
"""

from __future__ import annotations

import io
from typing import Any

from fontTools.ttLib import TTFont, TTLibError

from loremfile.catalog import Fixture
from loremfile.config import SOURCE_DATE_EPOCH
from loremfile.generators.font import FIRST_CODE, LAST_CODE, MAC_EPOCH_OFFSET
from loremfile.validators import ValidationError, register

#: What each format's file must be: (WOFF flavour, whether outlines are CFF).
SHAPES = {
    "ttf": (None, False),
    "otf": (None, True),
    "woff": ("woff", False),
    "woff2": ("woff2", False),
}
FIXED_TIMESTAMP = SOURCE_DATE_EPOCH + MAC_EPOCH_OFFSET


@register("ttf")
@register("otf")
@register("woff")
@register("woff2")
def validate_font(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    try:
        font = TTFont(io.BytesIO(data))
        order = font.getGlyphOrder()
        cmap = font.getBestCmap()
    except (TTLibError, KeyError, ValueError) as exc:
        raise ValidationError(f"is not a readable font: {exc}") from exc

    flavor, wants_cff = SHAPES[fixture.format]
    if font.flavor != flavor:
        raise ValidationError(f"is flavour {font.flavor!r}, not {flavor!r}")
    if wants_cff and "CFF " not in font:
        raise ValidationError("has no CFF table, so it carries no PostScript outlines")
    if not wants_cff and "glyf" not in font:
        raise ValidationError("has no glyf table, so it carries no TrueType outlines")

    head = font["head"]
    if head.created != FIXED_TIMESTAMP or head.modified != FIXED_TIMESTAMP:
        raise ValidationError(
            f"head carries {head.created}/{head.modified}, not the fixed {FIXED_TIMESTAMP}: "
            "a build-time stamp would move the hash on every run"
        )
    missing = [code for code in range(FIRST_CODE, LAST_CODE + 1) if code not in cmap]
    if missing:
        raise ValidationError(f"{len(missing)} printable ASCII codepoints are unmapped")
    if font["OS/2"].fsType != 0:
        raise ValidationError("OS/2 fsType restricts embedding, which a CC0 font must not")

    return {
        "glyphs": len(order),
        "cmap_entries": len(cmap),
        "units_per_em": head.unitsPerEm,
        "family": font["name"].getDebugName(1),
        "outlines": "cff" if "CFF " in font else "glyf",
        "flavor": font.flavor or "",
        "embeddable": font["OS/2"].fsType == 0,
    }
