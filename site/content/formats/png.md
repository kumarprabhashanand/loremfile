PNG is the lossless image format of the web, and the one most image tools are checked
against first. These files are the loremfile colour-bar test card, with a border, a centre
cross and a label giving the dimensions and mode.

`png/100x100.png`, `png/640x480.png` and `png/1920x1080.png` are RGB at common sizes, and
`png/1x1.png` is a single white pixel, the smallest useful PNG. `png/transparent-256x256.png`
adds a horizontal alpha ramp, so transparency is visible rather than uniform, and
`png/grayscale-512x512.png` is 8-bit greyscale, which catches code that assumes three
channels.

`png/animated-apng-10frames-128x128.png` is an animated PNG of ten frames at 100 ms, with the
colour bars rotating a step each frame. A decoder without APNG support shows only one frame,
which is worth knowing before a resize step flattens it. For size limits, `png/1mb.png` is
about 1 MB of seeded RGB noise that does not compress.

Related formats: [JPEG](/jpg), [WebP](/webp), [AVIF](/avif), [GIF](/gif) and [SVG](/svg).
