`jpg/exif-orientation-6-640x480.jpg` and `jpg/exif-orientation-8-640x480.jpg` store their
pixels at 480x640 and carry EXIF orientations 6 and 8: a viewer that honours the tag shows them
upright at 640x480, and one that ignores it shows them sideways.

`jpg/cmyk-640x640.jpg` is CMYK, which a pipeline that assumes RGB converts wrongly or refuses.
`jpg/progressive-1920x1080.jpg` is progressive, decoded in passes, where `jpg/1920x1080.jpg` is
baseline at the same size: 30,994 bytes against 56,817, and a decoder that supports only
baseline fails on the first.

`jpg/4000x3000.jpg` is 4000x3000 in 279,204 bytes, for decoders and thumbnailers that must
downscale a large frame. `jpg/100x100.jpg` and `jpg/640x480.jpg` are small RGB test cards,
4,615 and 14,992 bytes. `jpg/1mb.jpg` and `jpg/10mb.jpg` are 991,379 and 10,006,097 bytes of
seeded noise, for upload limits that need a real image of a known size.
