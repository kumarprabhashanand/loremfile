WOFF is the web font wrapper: a TrueType or CFF font with a compressed table structure and a
little metadata, designed to be served over HTTP.

`woff/loremfile-sans.woff` is "Loremfile Sans" in that wrapper — 95 printable ASCII glyphs,
each a rectangle whose width is computed from the character's codepoint. The family is
generated rather than derived from any existing typeface, so there is nothing to license and
nothing to attribute.

Publishing the same family in four wrappers is the point. A conversion tool, a subsetter or a
loader can be checked against a reference rather than against its own output, and a renderer
that handles one wrapper but not another shows up immediately.

Use it to test `@font-face` loading over the network, font parsing, subsetting and conversion,
and content-type handling — it is served as `font/woff`, which not every server knows. Related
formats: [WOFF2](/woff2), which compresses better and is what you should serve today,
[TTF](/ttf) and [OTF](/otf).
