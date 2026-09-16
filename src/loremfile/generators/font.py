"""The "Loremfile Sans" font family (docs/05 §3.9, ADR-018).

Every glyph is a rectangle whose size and advance are computed from its codepoint, so the
family is generated rather than derived: no outline here is traced from a third-party
typeface, and text set in it renders as visible blocks. That is what a font fixture has to
prove — that a renderer loaded the file, mapped a codepoint, and advanced by the declared
width — and blocks show a missing mapping far more clearly than letters would.
"""

from __future__ import annotations

from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

from loremfile.generators.base import GeneratorContext, generator

UNITS_PER_EM = 1000
ASCENDER = 800
DESCENDER = -200
#: Printable ASCII: the range a test string is drawn from.
FIRST_CODE = 0x20
LAST_CODE = 0x7E
#: Seconds between 1904-01-01 and 1970-01-01. `head` counts from the earlier epoch, and
#: fontTools would otherwise stamp the build time into two fields of every file.
MAC_EPOCH_OFFSET = 2082844800
FAMILY = "Loremfile Sans"
STYLE = "Regular"
POSTSCRIPT_NAME = "LoremfileSans-Regular"
VERSION = "Version 1.000"
LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


def glyph_name(code: int) -> str:
    return f"uni{code:04X}"


def advance_width(code: int) -> int:
    """A width that varies by codepoint, so a line of text has a visible rhythm."""
    return 300 + (code % 7) * 50


def box(code: int) -> tuple[int, int, int, int]:
    """The rectangle drawn for a codepoint: (xMin, yMin, xMax, yMax)."""
    inset = 40
    height = 300 + (code % 5) * 100
    return inset, 0, advance_width(code) - inset, height


def _draw(pen: TTGlyphPen | T2CharStringPen, code: int) -> None:
    left, bottom, right, top = box(code)
    pen.moveTo((left, bottom))
    pen.lineTo((left, top))
    pen.lineTo((right, top))
    pen.lineTo((right, bottom))
    pen.closePath()


def _names() -> dict[str, str]:
    return {
        "familyName": FAMILY,
        "styleName": STYLE,
        "uniqueFontIdentifier": f"{FAMILY} {VERSION}",
        "fullName": f"{FAMILY} {STYLE}",
        "psName": POSTSCRIPT_NAME,
        "version": VERSION,
        "licenseDescription": (
            "Dedicated to the public domain under CC0 1.0. No rights reserved; "
            "the outlines are generated rectangles, not derived from any typeface."
        ),
        "licenseInfoURL": LICENSE_URL,
        "vendorURL": "https://loremfile.dev/",
    }


def _build(*, cff: bool, epoch: int) -> FontBuilder:
    """A complete font: glyph order, cmap, outlines, metrics, names, OS/2 and post."""
    codes = list(range(FIRST_CODE, LAST_CODE + 1))
    order = [".notdef", *(glyph_name(code) for code in codes)]
    builder = FontBuilder(UNITS_PER_EM, isTTF=not cff)
    builder.font.recalcTimestamp = False
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({code: glyph_name(code) for code in codes})

    if cff:
        charstrings = {}
        for name, code in ((glyph_name(code), code) for code in codes):
            pen = T2CharStringPen(advance_width(code), None)
            _draw(pen, code)
            charstrings[name] = pen.getCharString()
        empty = T2CharStringPen(advance_width(FIRST_CODE), None)
        empty.moveTo((0, 0))
        empty.closePath()
        charstrings[".notdef"] = empty.getCharString()
        builder.setupCFF(POSTSCRIPT_NAME, {"FullName": f"{FAMILY} {STYLE}"}, charstrings, {})
    else:
        glyphs = {}
        for code in codes:
            pen = TTGlyphPen(None)
            _draw(pen, code)
            glyphs[glyph_name(code)] = pen.glyph()
        glyphs[".notdef"] = TTGlyphPen(None).glyph()
        builder.setupGlyf(glyphs)

    metrics = {glyph_name(code): (advance_width(code), box(code)[0]) for code in codes}
    metrics[".notdef"] = (advance_width(FIRST_CODE), 0)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=ASCENDER, descent=DESCENDER)
    builder.setupNameTable(_names())
    builder.setupOS2(
        sTypoAscender=ASCENDER,
        sTypoDescender=DESCENDER,
        sTypoLineGap=0,
        usWinAscent=ASCENDER,
        usWinDescent=-DESCENDER,
        achVendID="LRMF",
        fsType=0,  # installable embedding: the family is CC0
    )
    builder.setupPost(isFixedPitch=0)
    # The two fields fontTools would otherwise fill from the clock.
    head = builder.font["head"]
    head.created = head.modified = epoch + MAC_EPOCH_OFFSET
    return builder


@generator(parallel_safe=False)
def family(ctx: GeneratorContext, *, cff: bool = False, flavor: str = "") -> Path:
    """One file of the family: TrueType outlines or CFF, optionally WOFF-compressed."""
    builder = _build(cff=cff, epoch=ctx.epoch)
    if flavor:
        builder.font.flavor = flavor
    suffix = flavor or ("otf" if cff else "ttf")
    target = ctx.workdir / f"{ctx.path.replace('/', '-')}-{suffix}"
    builder.save(str(target))
    return target
