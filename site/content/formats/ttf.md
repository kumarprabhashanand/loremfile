TrueType is the font format with the widest support, which makes it the baseline: if a loader
handles anything, it handles this.

`ttf/loremfile-sans.ttf` is "Loremfile Sans" — 95 printable ASCII glyphs, each drawn as a
rectangle whose width is computed from the character's codepoint. The family is generated
rather than derived from any existing typeface, so there is no licence to read and nothing to
attribute; like everything here it is CC0.

The rectangles are deliberate. They make metrics visible to the naked eye, so a renderer that
ignores advance widths or applies the wrong scale is obvious immediately, and they keep the
file small enough to commit to a test suite without thinking about it.

Use it to test font loading and parsing, `@font-face` handling, metrics extraction, subsetting
and conversion between wrappers. The same family is published as [OTF](/otf),
[WOFF](/woff) and [WOFF2](/woff2), so a conversion can be checked against a reference.
