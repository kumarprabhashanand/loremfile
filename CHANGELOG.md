# Changelog

## [Unreleased]

## [1.8.0] - 2026-10-11

- `jpg/cmyk-640x640.jpg` replaces `jpg/cmyk-640x480.jpg`, which has measured 640x640 since it
  was published under a 640x480 name. The old URL keeps serving the same bytes, and its entry
  now carries `supersededBy` and `deprecated`.
- Catalog text without em dashes: 75 format titles first, then 13 format descriptions and 17
  fixture descriptions, reworded with the same meaning. The files are unchanged.

## [1.7.0] - 2026-10-11

- `m4a/aac-64k-44k-30s.m4a`: AAC at 64 kbps and 44.1 kHz, beside the 128 kbps, 48 kHz file.
- `opus/cbr-32k-30s.opus`: Opus at a constant 32 kbps.
- `wav/sine-440hz-3s-48k-24bit-stereo.wav`: 24-bit PCM behind the 68-byte extensible header.
- `md/long-with-toc-and-footnotes.md`: a long document whose contents links and footnotes all resolve.
- `docx/anchored-image-with-alt-text.docx`: one JPEG floating in an anchor, with alt text.
- `hls/multi-bitrate/master.m3u8`: a master playlist over a new 360p rendition in `hls/360p-10s/`
  and the existing 720p one, its BANDWIDTH, RESOLUTION and CODECS measured from the segments.
- New measured props, existing bytes unchanged: `bitrate_kbps` from the audio packets and
  `bit_depth` for PCM on every audio file, the WAV header's format and size, the video
  profile and H.264 level, inline and anchored images and alt text on every DOCX, and
  headings, anchor links and footnotes on Markdown.
- Four audio descriptions now say what was measured: `opus/30s.opus` averages 114 kbps, not
  the 96 it was encoded for; `aac/adts-30s.aac` is 130.6 kbps with its frame headers;
  `ogg/vorbis-30s.ogg` no longer names an encoder quality; and the 3-second MP3's extra
  24 ms is one 1152-sample frame.

## [1.6.1] - 2026-10-11

- `contains_text` in the manifest: three to five strings each text-bearing PDF, DOCX, PPTX,
  XLSX, EPUB, HTML and Markdown file is known to contain, so a parser test can check what it
  read, not only that it read something. Compare by containment. The files are unchanged.

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
