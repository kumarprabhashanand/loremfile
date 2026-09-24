# Changelog

## [Unreleased]

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
