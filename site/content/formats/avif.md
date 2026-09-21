AVIF is an image format built on the AV1 video codec, with much better compression than JPEG
and support in current browsers. `avif/640x480.avif` is the loremfile colour-bar test card, a
border, a centre cross and a label giving the dimensions and mode, encoded with `avifenc` at
speed 6.

It was encoded single-threaded, which is what makes the output reproduce byte for byte. That
matters for a fixture: the hash in the manifest describes these exact bytes, and a
multithreaded encoder can produce different bytes on different machines.

Use it to test browser and library decoding, content-type sniffing, image upload forms that
claim AVIF support, and thumbnailers. The test card is the same one used for the PNG, JPEG
and WebP files, so you can compare decoded output across formats and spot a colour or
scaling difference at a glance. See also [WebP](/webp), [PNG](/png) and [JPEG](/jpg).
