WebP is Google's image format for the web, with lossy and lossless compression and an alpha
channel. Current browsers display it, but plenty of server-side image libraries and upload
validators still reject it.

`webp/lossy-640x480.webp` is the loremfile colour-bar test card saved as lossy WebP at
quality 80. Because the same card exists as PNG and JPEG, you can compare sizes and decoded
output across formats.

`webp/alpha-256x256.webp` is a lossless WebP with an alpha ramp, the case that breaks
converters which drop transparency or flatten it onto black. Lossless WebP uses a different
bitstream from lossy WebP, so a decoder that handles one does not necessarily handle the
other.

Use them to test image upload forms, thumbnailers, CDNs that convert formats, and code that
must recognise the `RIFF` header with a `WEBP` form type. Related formats: [PNG](/png),
[JPEG](/jpg) and [AVIF](/avif).
