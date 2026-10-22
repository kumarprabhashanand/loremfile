`png/transparent-256x256.png` is RGBA with an alpha ramp, so a pipeline that drops alpha or
composites onto black shows it wrong. `png/animated-apng-10frames-128x128.png` has 10 frames,
and a decoder that does not know APNG shows only the first, which is itself a valid PNG.

`png/grayscale-512x512.png` is a single greyscale channel (mode L), for code that assumes
three. `png/1x1.png` is one pixel in 69 bytes, the smallest valid PNG for upload and
placeholder paths.

`png/100x100.png`, `png/640x480.png` and `png/1920x1080.png` are RGB test cards at 1,387, 4,208
and 11,110 bytes, for resizers and thumbnailers. Each of `png/100x100.png`,
`png/640x480.png` and `png/1920x1080.png` prints its own dimensions and mode on the card, so a
resize or colour-mode bug shows in the output image itself. `png/1mb.png` is 1,000,147 bytes
of seeded noise at 1024x325, which PNG compression cannot shrink, for upload limits that need
a real image of a known size.
