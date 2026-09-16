JPEG is the default photo format, and the one every image upload accepts. These files are the
loremfile colour-bar test card at the sizes people actually need, plus the variants that
break naive decoders.

`jpg/100x100.jpg`, `jpg/640x480.jpg`, `jpg/1920x1080.jpg` and `jpg/4000x3000.jpg` are
baseline JPEGs at quality 85 with 4:2:0 chroma subsampling. `jpg/progressive-1920x1080.jpg`
is the same card saved as a progressive scan, which renders coarse to fine.

Two files target specific bugs. `jpg/cmyk-640x480.jpg` uses the CMYK colour space, which
pipelines expecting RGB mishandle. `jpg/exif-orientation-6-640x480.jpg` stores its pixels
rotated with EXIF orientation 6, so the label reads upright only when the viewer honours the
tag; a viewer that ignores EXIF shows it sideways.

For size limits, `jpg/1mb.jpg` and `jpg/10mb.jpg` are seeded noise at quality 95 with 4:4:4
sampling, so their size is honest. Related formats: [PNG](/png), [WebP](/webp),
[AVIF](/avif) and [TIFF](/tiff).
