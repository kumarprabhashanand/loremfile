TIFF is the format of scanners, print workflows and GIS, and it is flexible enough that
"supports TIFF" rarely means every TIFF. `tiff/rgb-640x480.tiff` is the common baseline case:
the loremfile colour-bar test card at 640x480, uncompressed RGB.

An uncompressed baseline TIFF is the file every TIFF reader must handle, so it is the right
starting point. If a tool fails here, it does not really support TIFF; if it succeeds here and
fails on a compressed or multi-page file from elsewhere, the gap is in those features. The
test card's border, centre cross and label make orientation and channel mistakes visible at a
glance.

Use it to test image upload forms, scanning pipelines, thumbnailers and converters. Most
browsers do not display TIFF, so it also checks that an upload flow converts or previews the
file rather than showing a broken image. Related formats: [PNG](/png), [BMP](/bmp) and
[JPEG](/jpg).
