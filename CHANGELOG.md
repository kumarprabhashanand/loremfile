# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the catalog version follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) as defined in
`docs/09-ci-cd.md` §7:

- **minor** — fixtures added or removed (tombstoned);
- **patch** — descriptions, tags, notes, deprecation flags or site-only changes
  (`props`, `bytes`, `sha256` and `mime` never change);
- **major** — a manifest schema or URL contract change. It never removes anything.

## [Unreleased]

The engineering narrative — how each part was built, what broke, and what was measured — lives in [`docs/20-engineering-log.md`](docs/20-engineering-log.md).

### Changed — what the site promises (owner decision, 2026-09-16)

- The terms of use now say what a free, non-commercial service can keep: no promise of
  availability, the bytes at a published path do not change, a file may be withdrawn in
  rare cases, and the service may be discontinued with notice where that is possible. They
  add the standard German liability split and a note that some files are deliberately
  malformed.
- Site copy drops permanence and availability claims; the detail lives in the terms.

### Added — the website (M4.1, M4.2)

- Pages: a home page with search, a page for each published format (77 today, one per format in `manifest.json`), all formats, documentation, legal pages, the changelog and status.
- Discovery files: `llms.txt`, `llms-full.txt`, `sitemap.xml`, `robots.txt`, `.well-known/security.txt`, `search-index.json`, and a list per format at `/{format}/index.json`.

### Added — the Impressum decision, and keeping the legal pages out of search and AI crawlers

The owner's decisions, recorded without any personal value. Rendering lands with M4.1; this
is the part that can land before it.

- **ADR-028**: loremfile.dev is **not *geschäftsmäßig* under § 5 DDG** — never offered for
  payment, no advertising, and the owner's cited position of the Berlin regulator (mabb)
  that an unpaid service is *geschäftsmäßig* only when regular advertising covers its
  costs. The Impressum follows **§ 18 Abs. 1 MStV**: name, a serviceable address and
  hello@loremfile.dev; no telephone number. **Reopen triggers**: any payment, advertising,
  sponsorship or affiliate link — and a second contact channel must be added **before**
  such a change ships. `docs/14`'s allowance for a "sponsored by" footer line is removed,
  and Q-12 is tied to the ADR.
- **The values exist only as production secrets** `IMPRINT_NAME`, `IMPRINT_STREET`,
  `IMPRINT_POSTAL_CITY` — separate plain secrets, never a JSON blob, since GitHub warns
  structured data can defeat log redaction. `docs/13` §3b holds the template with
  `%%IMPRINT_*%%` placeholders and the M4.1 rules: fill only in `production` jobs, hard-fail
  on a missing secret, assert no marker survives, never print or artifact a rendered page,
  and a `git grep -qF` guard proving no value entered git. **`AGENTS.md` rule 5**: never write
  the values anywhere, for any reason.
- **Q-07 and Q-21 are resolved without recording a value.** Q-21's basis is corrected: the
  serviceable-address requirement comes from § 18 MStV, not Art. 13 GDPR.
- **Header rule `legal_pages_noindex`** sets `X-Robots-Tag: noindex, nofollow, nosnippet` on
  exactly the two pages; transform rules go **5 → 6 of 10**. It applies on merge; its effect on
  real pages is verified when M4.1 publishes them. `docs/12` §4 no longer claims site pages carry
  no robots tag.
- **robots.txt (specified in `docs/04` §6)** keeps `User-agent: *` / `Allow: /` — Google honours
  `noindex` only on a page it may crawl — and adds one group disallowing only the two paths for
  `GPTBot`, `OAI-SearchBot`, `ChatGPT-User`, `ClaudeBot`, `Claude-User`, `Claude-SearchBot` and
  `Google-Extended`, each checked against its vendor's own documentation. Both pages are also
  excluded from `sitemap.xml`, `llms.txt`, `llms-full.txt`, `search-index.json` and all JSON-LD.
  **The limit is stated**: these reduce reading, they cannot prevent it (RFC 9309: robots.txt is
  "not a form of access authorization").
- **The WAF custom rule is a documented [VERIFY], not yet a rule** (`docs/08` §5.3). Established
  before any write: 0 of 5 custom rules used; `http.user_agent` has no stated plan restriction,
  so only a write can settle it; `Google-Extended` sends no user agent of its own and must never
  be matched; Anthropic's header strings are unconfirmed; and a full-`PUT` phase would delete any
  incident rule added in the dashboard, which the runbook must address first. It lands as its own
  pull request with a probe and a negative control.
- Also: `AGENTS.md` said the launch set is 229 of 417; it has been 228 of 416 since Q-22.

### Changed — immutability attaches on publication, not on entry into the manifest

- `docs/03` §7.1 and ADR-005 amended. What ADR-005 protects is embedded URLs and hashed
  fixtures in other people's tests, and **both require the bytes to have been served**.
  An entry that never reached R2 has no consumer and breaks no promise, so it is removed
  outright rather than tombstoned — a tombstone asserts a publication that never
  happened and would render as one on the format page. **Not a relaxation**: R2 bucket
  locks already implement exactly this boundary; the wording claimed more than the
  system enforced.
- **Five manifest entries withdrawn** — `mp4/1080p-10s.mp4`, `mp4/10mb.mp4`,
  `mp4/50mb.mp4`, `opus/30s.opus`, `webm/720p-5s-vp9.webm`. Verified against the CI
  artifact: three described bytes that existed nowhere in the world; two were captured
  in time by the new carry-forward artifact. All five are withheld together, and their
  catalog rows stay, marked `awaiting_publication` with the reason.
- `manifest update` performs the withdrawal, refusing any path present in the base
  branch manifest — withdrawing a *published* path stays forbidden.
- **New CI guard**: a path marked `expected_drift` that is new on this branch may not
  enter the manifest unless the bytes this run built match it. That is the check that
  would have caught this at M3.6 rather than after the fact.
- `docs/09` §3.1's listing still showed `new-fixtures: build/fixtures` two days after
  M3.1 replaced it. The stale line is corrected, and the episode is recorded there: the
  wrong fix was proposed *because the doc was trusted*.

### Added — video, audio and HLS (M3.6)

- `mp4/` (9), `webm/`, `mkv/`, `mov/`, `avi/`, `ogv/`, `ts/` (1 each), `hls/` (6),
  `mp3/` (7), `wav/` (2), `flac/`, `ogg/`, `opus/`, `m4a/`, `aac/`, `aiff/` (1 each) —
  36 launch fixtures. All synthetic: ffmpeg's `testsrc2` pattern and a 440 Hz tone, so
  no third-party footage or recording is redistributed.
- `generators/media_video.py`, `generators/media_audio.py`, `generators/hls.py`,
  `validators/media.py` (ffprobe, plus the structural checks ffprobe cannot make).
- `wav/10mb.wav` is **exactly** 10,000,000 bytes — an `exact` size class, not `approx`.
- `docs/06` §4 gains an ffmpeg row and marks mutagen verified.

### Added — office documents and e-books (M3.5)

- `docx/` (5), `xlsx/` (6), `pptx/` (3), `rtf/` (1), `epub/` (1) — 16 launch fixtures.
- `generators/office.py`, `validators/office.py`. The validators read every OOXML
  package a second time as a plain zip, because python-docx and openpyxl both read back
  their own conventions and will reopen a package Word would refuse.
- `xlsx/with-formulas.xlsx` carries **cached results** for every formula. openpyxl has no
  API for them and writes an empty `<v/>`, which reads back as `None` in pandas — a
  formula fixture without them parses perfectly and is useless.

### Added — PDF (M3.4)

- `pdf/` — 12 launch fixtures: A4 and Letter, portrait and landscape, with images,
  with a table, encrypted, blank, a hand-written minimal file, and two sized.
- `generators/pdf.py`, `validators/pdf.py` (pypdf plus `qpdf --check`).

### Added — images (M3.3)

- `png/` (8), `jpg/` (9), `gif/` (2), `webp/` (2), `avif/` (1), `bmp/` (1), `tiff/` (1),
  `ico/` (1), `svg/` (2) — 27 launch fixtures.
- `generators/image.py`, `generators/svg.py`, `validators/image.py`.

### Added — columnar, database and geographic formats (M3.2b)

- `parquet/` (2), `arrow/` (1), `avro/` (1), `sqlite/` (2), `geojson/` (1), `gpx/` (1),
  `kml/` (1), `kmz/` (1) — 10 launch fixtures.
- `generators/columnar.py`, `generators/geo.py`, `validators/columnar.py`,
  `validators/geo.py`.

### Added — data formats (M3.2a)

- `csv/` (8), `tsv/` (1), `json/` (6), `ndjson/` (1), `xml/` (3), `yaml/` (1),
  `toml/` (1), `sql/` (1) — 22 launch fixtures, all serialising the shared `people`
  dataset so the same record can be compared across formats.
- `generators/data.py`, `validators/data.py`.

### Added — first fixtures

- `bin/` (23 fixtures, 230,715,033 bytes) and the text formats `txt/`, `md/`, `log/`,
  `ini/` (20 fixtures): generators, validators, catalogs, and the first `manifest.json`,
  `sha256sums.txt` and `formats.json` (M3.1).
- `loremfile build` and `loremfile validate`; the `build-and-validate` CI job.

### Changed

- **Q-22 resolved: `bin/100mib.bin` is phase 2, and the launch set is 228 fixtures, not
  229.** At 104,857,600 bytes it exceeded REQ-23's 100,000,000-byte cap while being
  listed phase 1. Deferred rather than excepted — nothing gets an exception at launch.
  Phase-1 total 417 → 416; P1b stays 188. `docs/05` §3.10's phase-2 note now states the
  real reason on all three deferred rows instead of "storage budget".

- `docs/13-legal-and-policy.md` §3 privacy notice rewritten and §3a "Compliance posture"
  added; §8 replaced with a per-regime posture table. The previous rationale — "no
  personal data is collected by us" — was wrong: IP addresses are personal data,
  Cloudflare is the processor and the owner is the controller.
- `docs/06-generation-pipeline.md` §9: the three M1.2 `[VERIFY]` items resolved against
  the built image — ffmpeg encoders (including `libx265` and `libsvtav1`), SQLite FTS5,
  and the absence of a zstd mode in Python 3.12's `tarfile`.
- `THIRD_PARTY.md`: the Python-libraries table filled in from installed package metadata,
  with a note on the three copyleft dependencies.

## [1.1.0] - 2026-09-16

### Added — the launch set is complete (M3.7, M3.8)

- 62 fixtures: archives, fonts (`ttf`, `otf`, `woff`, `woff2`), mail (`eml`, `mbox`),
  calendar and contacts (`ics`, `vcf`), certificates (`pem`, `der`), WebAssembly, and the
  remaining web and text formats. Every file `docs/05` §9 lists for launch day now exists.
- A new `edge/` family: 19 files that are wrong on purpose — empty, truncated, mislabelled,
  malformed, and one archive whose entry name escapes the extraction directory. Each is
  served as the type its extension claims, so they test what your code does with input it
  should refuse rather than input it can read.

Every path added in this version, by format:

- **7z:** `7z/3-text-files.7z`
- **bz2:** `bz2/lorem-1mb.txt.bz2`
- **css:** `css/basic.css`
- **der:** `der/self-signed-ed25519-cert.der`
- **edge:** `edge/csv-ragged-rows.csv`, `edge/jpg-truncated-50pct.jpg`, `edge/json-bom.json`, `edge/json-trailing-comma.json`, `edge/mp4-truncated-50pct.mp4`, `edge/pdf-truncated-60pct.pdf`, `edge/pdf-with-png-extension.png`, `edge/png-with-pdf-extension.pdf`, `edge/utf8-invalid-bytes.txt`, `edge/xml-unclosed-tag.xml`, `edge/zero-byte.csv`, `edge/zero-byte.json`, `edge/zero-byte.mp4`, `edge/zero-byte.pdf`, `edge/zero-byte.png`, `edge/zero-byte.txt`, `edge/zero-byte.zip`, `edge/zip-directory-traversal-name.zip`, `edge/zip-truncated-50pct.zip`
- **eml:** `eml/plain-text.eml`, `eml/with-attachments.eml`
- **gz:** `gz/lorem-1mb.txt.gz`, `gz/multi-member-3.gz`
- **har:** `har/simple-3-requests.har`
- **html:** `html/all-elements.html`, `html/basic.html`, `html/with-inline-css.html`, `html/with-inline-js.html`
- **ics:** `ics/recurring-weekly-rrule.ics`, `ics/single-event.ics`
- **ipynb:** `ipynb/simple-with-outputs.ipynb`
- **js:** `js/hello-console.js`
- **mbox:** `mbox/3-messages.mbox`
- **md:** `md/all-elements.md`
- **otf:** `otf/loremfile-sans.otf`
- **pem:** `pem/self-signed-ed25519-cert.pem`
- **srt:** `srt/3-cues.srt`
- **tar:** `tar/3-text-files.tar`, `tar/3-text-files.tar.gz`, `tar/3-text-files.tar.xz`
- **ttf:** `ttf/loremfile-sans.ttf`
- **vcf:** `vcf/vcard3-single.vcf`, `vcf/vcard4-single.vcf`
- **vtt:** `vtt/3-cues.vtt`
- **wasm:** `wasm/minimal-add.wasm`
- **webmanifest:** `webmanifest/site.webmanifest`
- **woff:** `woff/loremfile-sans.woff`
- **woff2:** `woff2/loremfile-sans.woff2`
- **xz:** `xz/lorem-1mb.txt.xz`
- **zip:** `zip/100mb.zip`, `zip/10mb.zip`, `zip/1mb.zip`, `zip/3-text-files.zip`, `zip/aes256-password-loremfile.zip`, `zip/empty.zip`, `zip/mixed-fixtures.zip`, `zip/nested-directories.zip`
- **zst:** `zst/lorem-1mb.txt.zst`
