# Third-party components

Fixtures published by loremfile.dev are **generated**, not redistributed: no third-party
image, audio, video, text or font ships inside them. This file lists the tools and
libraries used to *produce* them, and their licences.

Entries are added by the milestone that introduces the dependency. Every addition must
also appear in `tools/requirements.in`, be pinned with hashes in `tools/requirements.lock`,
and bump `tools/TOOLCHAIN_DIGEST` in the same pull request (`tools/check_lock.sh` fails
otherwise).

## System packages (Debian, inside the toolchain image only)

| Package | Licence | Used for | Redistributed? |
|---|---|---|---|
| ffmpeg and its codec libraries (libx264, libvpx, libopus, libvorbis, libmp3lame, aac, flac, theora, prores_ks) | LGPL-2.1-or-later / GPL-2.0-or-later depending on the build | Generating the audio and video fixtures | **No** — used as a build tool; only its output (which is not copyrightable third-party content) is published |
| qpdf | Apache-2.0 | PDF linearisation and validation | No |
| libavif-bin, zstd, xz-utils, bzip2, sqlite3 | BSD-2/3-Clause, Public domain (SQLite) | AVIF, archive and SQLite fixtures | No |
| fonts-dejavu-core | Bitstream Vera Fonts Copyright / Arev Fonts Copyright | Rasterising label text into a few images and PDFs. Glyph *outlines* are never embedded as font data in a published fixture; the font itself is not redistributed. The `font/` fixtures are a generated box-glyph font (ADR-018), not DejaVu | No |
| git, gh, ca-certificates, curl | GPL-2.0, MIT, MPL-2.0, curl licence | CI plumbing inside the image | No |

## Python libraries

| Library | Licence | Used for |
|---|---|---|
| _(added per milestone — see `tools/requirements.in`)_ | | |

## Licences of what this repository publishes

| What | Licence |
|---|---|
| Generated fixtures (everything under a format path) | CC0 1.0 Universal — [`LICENSES/CC0-1.0.txt`](LICENSES/CC0-1.0.txt) |
| Source code, templates, documentation | MIT — [`LICENSE`](LICENSE) |
| Website text and graphics | CC BY 4.0, attribute "loremfile.dev" |

See [`docs/13-legal-and-policy.md`](docs/13-legal-and-policy.md) §1 for the reasoning.
