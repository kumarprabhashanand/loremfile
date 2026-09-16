OpenType with CFF outlines is the other half of the font question: many loaders handle
TrueType and quietly fail on CFF, or accept the file and render nothing.

`otf/loremfile-sans.otf` is "Loremfile Sans" in that form — 95 printable ASCII glyphs, each
drawn as a rectangle whose width is computed from the character's codepoint. The family is
generated rather than derived from any existing typeface, so there is no licence to read and
nothing to attribute: it is CC0 like everything else here.

Rectangles are a deliberate choice. They make the metrics obvious to the eye — you can see at
a glance whether a renderer is applying widths correctly — and they keep the file small enough
to embed in a test suite.

Use it to test font loading, `@font-face` handling, metrics extraction, subsetting and
conversion. The same family is published in three other wrappers: [TTF](/ttf),
[WOFF](/woff) and [WOFF2](/woff2).
