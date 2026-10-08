# Changelog

## [Unreleased]

## [1.6.0] - 2026-10-08

- `jpg/exif-orientation-8-640x480.jpg`: an EXIF rotation case for viewers that ignore orientation tags.
- `mp4/non-faststart-720p-5s.mp4`: metadata at the end, so sequential playback waits for the download.
- `zip/zip64-70000-empty-files.zip`: 70,000 empty members force ZIP64 central-directory handling.
- `pdf/scanned-1page.pdf`: readable raster text with no text layer, so extraction returns an empty string.
- `docx/with-tracked-changes.docx`: an insertion, a deletion and one comment for revision-aware extraction.
- `txt/utf16be-no-bom.txt`: UTF-16 big-endian text without a byte-order marker for encoding detection tests.

## [1.5.0] - 2026-10-07

- `heic/640x480.heic`: the colour-bar test card as HEIC, the format iPhones capture photos in,
  for testing upload forms and converters. A new format.
- `csv/people-10-crlf.csv`: the ten people rows with every record ending in CR LF.
- `pdf/form-fields-1page.pdf`: a fillable form of four text fields and two checkboxes, half of
  them filled.
- `xlsx/3sheets-with-formulas.xlsx`: three sheets, with summary formulas that read the other
  two through a quoted sheet name, results cached.
- New manifest props on these entries: the HEIC container's brands and primary item,
  `form_fields` and `filled_fields` for a PDF form, and `cross_sheet_formulas` for workbooks.

## [1.4.0] - 2026-09-28

- Two polyglots: `edge/pdf-zip-polyglot.pdf` and `edge/gif-zip-polyglot.gif` are each valid
  as two formats at once, for testing what your type detection does when the bytes do not
  decide. Scanners and proxies sometimes refuse polyglots — the `/edge` page says so.

## [1.3.1] - 2026-09-28

- Three of the broken files describe their damage in terms of their own bytes rather than
  one parser's error message. The files are unchanged.

## [1.3.0] - 2026-09-24

- `csv/people-10-quoted-commas.csv`: ten people rows with a comma inside a
  quoted field, for parsers that split on commas.
- The 19 broken files now say what is wrong with them, in manifest.json and on the site: one
  sentence about the damage, a valid file of the same type to compare against, and whether a
  reader must fail, may recover, or may do either.

## [1.2.0] - 2026-09-22

- 5 more media files: H.264 MP4 at 1080p for 10 seconds, at 10 MB and at 50 MB, a 30-second Opus
  file and a 720p VP9 WebM.

## [1.1.0] - 2026-09-16

First public release.

- 223 sample files in 77 formats — documents, images, audio, video, office files, data,
  archives, fonts and text — all CC0.
- 19 files broken on purpose (truncated, empty, malformed) for testing error handling.
- A SHA-256 for every file in manifest.json and sha256sums.txt, and a full archive on the
  GitHub release for mirroring.
- A website with a page per format, search, and llms.txt for AI agents.
