This is a sample TIFF file: an uncompressed RGB test card, free to hotlink or download.

<!-- file: tiff/rgb-640x480.tiff -->

`tiff/16bit-gray-big-endian-640x480.tiff` begins with `MM`, so every multi-byte value in it, from
the tag offsets to its 16-bit samples, is big-endian, and a reader that assumes little-endian
fails to open it or reads its samples byte-swapped. `tiff/rgb-640x480.tiff` begins with `II`,
the little-endian order, so a reader that assumes big-endian fails on it, and it is also the
baseline every reader must handle: 8-bit RGB, uncompressed, in a single strip.

`tiff/lzw-640x480.tiff`, `tiff/cmyk-640x480.tiff` and `tiff/multipage-3pages.tiff` are
little-endian like the baseline, so none of them shows a byte-order bug, which only
`tiff/16bit-gray-big-endian-640x480.tiff` does. `tiff/lzw-640x480.tiff` is 640x480 RGB too,
compressed with LZW and cut into many strips, so a decoder built without LZW, or a reader that
expects one strip, fails on it and not on the baseline.

`tiff/multipage-3pages.tiff` chains 3 images, each 640x480 RGB and uncompressed, so a reader
that stops after the first image shows one page of 3. `tiff/cmyk-640x480.tiff` stores cyan,
magenta, yellow and black at 8 bits each, so an RGB-only converter or thumbnailer drops a
channel or reads the colours wrong.
