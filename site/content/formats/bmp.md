BMP is the Windows bitmap format: a small header followed by pixels, usually uncompressed. It
is simple to write and still appears in scanners, legacy software and clipboard exports, so
image pipelines are expected to accept it.

`bmp/24bit-256x256.bmp` is the loremfile colour-bar test card at 256x256 pixels, stored as
uncompressed 24-bit BMP. The card has a border, a centre cross and a label giving the
dimensions and mode, so a decoder that flips rows or swaps colour channels shows it
immediately. BMP usually stores rows bottom-up and pixels in blue-green-red order, and both
are classic sources of upside-down or blue-tinted images.

Use it to test image upload forms, thumbnail generators and converters. Because the file is
uncompressed, its size follows directly from its dimensions, which also makes it handy for
checking that a resize or conversion step really ran. Compare it with the same test card as
[PNG](/png) or [TIFF](/tiff).
