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

Direct dependencies from `tools/requirements.in`, with the versions resolved into
`tools/requirements.lock` in M1.2. **Licences below were read from each installed
package's own metadata inside the built image on 2026-09-07**, not copied from memory.
The lock pins 89 packages in total (these plus their transitive dependencies), each with
hashes; regenerate the table with `tools/licences.py` after any dependency change.

| Library | Version | Licence | Used for |
|---|---|---|---|
| `fpdf2` | 2.8.8 | LGPL-3.0-only | PDF generation |
| `pypdf` | 6.17.0 | BSD-3-Clause | PDF validation |
| `python-docx` | 1.2.0 | MIT | DOCX |
| `openpyxl` | 3.1.5 | MIT | XLSX |
| `python-pptx` | 1.0.2 | MIT | PPTX |
| `pillow` | 12.3.0 | MIT-CMU | Raster images |
| `pyarrow` | 25.0.1 | Apache-2.0 | Parquet, Arrow |
| `fastavro` | 1.12.2 | MIT | Avro |
| `ijson` | 3.5.1 | BSD-3-Clause AND ISC | Streaming JSON validation |
| `lxml` | 6.1.3 | BSD-3-Clause | XML, SVG |
| `PyYAML` | 6.0.3 | MIT | YAML, the catalog loader |
| `tomli_w` | 1.2.0 | MIT | TOML |
| `jsonschema` | 4.26.0 | MIT | Manifest schema checks |
| `py7zr` | 1.1.3 | LGPL-2.1-or-later | 7z archives |
| `pyzipper` | 0.4.0 | MIT | Encrypted zip |
| `zstandard` | 0.25.0 | BSD-3-Clause | `.tar.zst` (Python 3.12's `tarfile` has no zstd mode) |
| `fonttools` | 4.64.0 | MIT | The generated font family, WOFF/WOFF2 |
| `brotli` | 1.2.0 | MIT | WOFF2 compression |
| `mutagen` | 1.48.1 | GPL-2.0-or-later | Audio tag validation |
| `markdown-it-py` | 4.2.0 | MIT | Site content rendering |
| `html5lib` | 1.1 | MIT | HTML fixture validation |
| `icalendar` | 7.3.0 | BSD-2-Clause | ICS |
| `vobject` | 0.9.9 | Apache-2.0 | VCF |
| `cryptography` | 50.0.1 | Apache-2.0 OR BSD-3-Clause | The Ed25519 test certificate |
| `pydantic` | 2.13.5 | MIT | Catalog and manifest models |
| `click` | 8.5.0 | BSD-3-Clause | The CLI |
| `Jinja2` | 3.1.6 | BSD-3-Clause | Site templates |
| `boto3` | 1.43.89 | Apache-2.0 | R2 uploads over the S3 API |
| `requests` | 2.34.2 | Apache-2.0 | Cloudflare API, live verification |
| `pytest` | 9.1.1 | MIT | Tests |
| `responses` | 0.26.3 | Apache-2.0 | HTTP fakes in tests |
| `ruff` | 0.16.6 | MIT | Lint and format |
| `mypy` | 2.3.1 | MIT | Type checking |
| `types-requests` | 2.33.0.20260906 | Apache-2.0 | Stubs |
| `types-PyYAML` | 6.0.12.20260906 | Apache-2.0 | Stubs |
| `boto3-stubs` | 1.43.89 | MIT | Stubs |
| `pip-tools` | 7.6.1 | BSD-3-Clause | Regenerating the lock |

Three transitive dependencies are worth naming because they are unfamiliar and were
checked against PyPI in M1.2 rather than assumed: `ast-serialize` and `librt` are mypy's
own components (github.com/mypyc, same maintainers as mypy), and `backports-zstd` is a
backport of `compression.zstd` pulled in by `py7zr`.

### Copyleft dependencies, and why they do not change this project's licence

Three of the above are copyleft: `fpdf2` (LGPL-3.0-only), `py7zr` (LGPL-2.1-or-later) and
**`mutagen` (GPL-2.0-or-later)**. They are *build-time tools*, on the same footing as
ffmpeg: this repository ships MIT-licensed source and a `Dockerfile` that installs them
from PyPI when the image is built. No combined work is distributed — no binary, no
vendored copy, no wheel. What is published on loremfile.dev is generated *data* (PDFs,
archives, audio files), which is not a derivative work of the library that wrote it, and
which carries CC0 in any case.

The one worth the owner's attention is `mutagen`, because GPL is stronger than the LGPL
of the other two and because it is imported into the same Python process rather than run
as a subprocess. It is used only to read audio tags back during validation. If the owner
would prefer no GPL import at all, `ffprobe` already covers most of the same ground — but
that is a preference, not a licence problem with the current arrangement.

## Licences of what this repository publishes

| What | Licence |
|---|---|
| Generated fixtures (everything under a format path) | CC0 1.0 Universal — [`LICENSES/CC0-1.0.txt`](LICENSES/CC0-1.0.txt) |
| Source code, templates, documentation | MIT — [`LICENSE`](LICENSE) |
| Website text and graphics | CC BY 4.0, attribute "loremfile.dev" |

See [`docs/13-legal-and-policy.md`](docs/13-legal-and-policy.md) §1 for the reasoning.
