WOFF2 is the web font format to serve today: the same outlines as a TrueType or CFF font,
compressed with Brotli, typically a third smaller than WOFF.

`woff2/loremfile-sans.woff2` is "Loremfile Sans" in that wrapper — 95 printable ASCII glyphs,
each drawn as a rectangle whose width is computed from the character's codepoint. The family
is generated rather than derived from any existing typeface, so there is no licence to read
and nothing to attribute.

The compression is what makes this one worth testing separately. A loader that handles WOFF
may not handle WOFF2 at all, and a build pipeline that rewrites or re-compresses assets can
corrupt the Brotli stream in ways that only show up when a browser tries to use the font.

Use it to test `@font-face` loading, font parsing, subsetting, conversion and content-type
handling; it is served as `font/woff2`. The same family is published as [WOFF](/woff),
[TTF](/ttf) and [OTF](/otf).
