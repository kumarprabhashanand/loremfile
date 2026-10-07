HEIC is an image coded with HEVC (H.265) inside a HEIF container, the format iPhones capture
photos in by default. `heic/640x480.heic` is the loremfile colour-bar test card, a border, a
centre cross and a label giving the dimensions and mode, encoded with `heif-enc` at quality
60.

Browser support is the reason to test it. Of the major browsers only Safari, from version 17,
decodes HEIC, so an upload form that takes photos straight from a phone has to convert the
file, refuse it with a clear message, or store it untouched. This file shows which of the
three yours does, and whether its type detection recognises the `heic` brand in the file's
`ftyp` box rather than trusting the extension.

It was encoded single-threaded with x265's assembly turned off, which is what makes the output
reproduce byte for byte. The test card is the same one used for the PNG, JPEG, WebP and AVIF
files, so a decoded HEIC can be compared with them directly. See also [AVIF](/avif),
[JPEG](/jpg) and [PNG](/png).
