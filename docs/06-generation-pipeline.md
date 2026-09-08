# 06 — Generation Pipeline

Everything here runs inside the pinned toolchain container (§9), locally or in GitHub Actions. Language: Python 3.12. Package: `src/loremfile/` installed with `pip install -e .`. Entry point: `loremfile` CLI (`python -m loremfile`).

## 1. Repository layout (source)

```
src/loremfile/
├── __init__.py            # __version__
├── cli.py                 # click-based CLI (see §10)
├── ci_summary.py          # renders manifest-check JSON into a GitHub step summary
├── gh_issue.py            # opens/updates/closes GitHub issues from health/audit reports (uses the gh CLI)
├── release.py             # builds delta/snapshot archives for GitHub Releases
├── config.py              # SITE_HOST, BASE_URL, BUCKET, limits, SOURCE_DATE_EPOCH
├── catalog.py             # load + validate catalog/*.yaml (pydantic models)
├── manifest.py            # load/save/lock-check manifest.json, sha256sums.txt, per-format index
├── datasets.py            # people/orders/products deterministic datasets
├── util/
│   ├── determinism.py     # seeded RNG helpers, fixed timestamps, env guard
│   ├── zipnorm.py         # normalise any zip-based file (docx/xlsx/pptx/epub/kmz/zip) to fixed mtimes + order
│   ├── lorem.py           # lorem ipsum corpus + multilingual corpora
│   ├── sizing.py          # pad/trim helpers, size classes, decimal vs binary units
│   └── ffmpeg.py          # ffmpeg/ffprobe wrappers with bitexact flags
├── generators/            # one module per family; each exposes functions named in the catalog
│   ├── base.py            # GeneratorContext, @generator decorator (parallel_safe), registry
│   ├── pdf.py image.py svg.py media_video.py media_audio.py hls.py office.py text.py
│   ├── data.py geo.py archive.py font.py binary.py web.py mail.py calendar.py cert.py wasm.py edge.py
├── validators/            # one module per family; each returns a props dict and raises on failure
│   ├── __init__.py        # dispatch by format; common checks (size class, magic bytes, policy)
│   ├── pdf.py image.py media.py office.py text.py data.py archive.py font.py binary.py mail.py cert.py wasm.py edge.py
│   └── policy.py          # content policy scan (private keys, EICAR, executables, external entities)
├── site/                  # builder (Jinja2), templates in /site at repo root
│   ├── build.py
│   └── serve.py           # local preview server mapping extensionless keys to text/html and / to index.html
├── data/wordlists/        # first_names.txt, last_names.txt, cities.txt, streets.txt, countries.txt, latin1_words.txt (synthetic, CC0)
├── data/scripts/          # per-script character inventories for pseudo-text (05 §7)
├── data/emoji.txt         # fixed emoji sequence list (05 §7)
├── ops_log.py             # appends the weekly metrics line to ops-log.md on the ops-log branch (health.yml)
├── usage.py               # GraphQL Analytics reads (R2 operations, zone traffic) with the read-only token
├── upload.py              # boto3 uploader (R2 S3 API)
├── infra/
│   ├── apply.py audit.py cloudflare_api.py
├── verify_live.py         # live contract checks
└── schema/manifest-v1.json
```

## 2. `config.py`

```python
OWNER = "<OWNER>"                        # GitHub owner; replace once Q-03 is answered (grep -rn "<OWNER>")
SITE_HOST = "loremfile.dev"
BASE_URL = f"https://{SITE_HOST}/"
BUCKET = "loremfile-public"
SOURCE_DATE_EPOCH = 1577836800            # 2020-01-01T00:00:00Z
MAX_FIXTURE_BYTES = 100_000_000           # REQ-23
MAX_TOTAL_BYTES = 8_000_000_000           # REQ-24
APPROX_TOLERANCE = 0.05                   # REQ-12
FIXTURE_CACHE_CONTROL = "public, max-age=31536000, immutable, no-transform"
SITE_CACHE_CONTROL = "public, max-age=300, must-revalidate"
ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
BUILD_DIR = "build"                       # build/fixtures/<path>, build/site/<key>
```

All modules read from here; nothing else hard-codes the host.

## 3. Catalog YAML schema (`catalog/{format}.yaml`)

```yaml
format: pdf
family: documents            # one of: documents, images, video, audio, data, text, web, archives, fonts, binary, calendar-mail, certificates, edge
mime: application/pdf        # default Content-Type for the format; text formats include "; charset=utf-8"
description: Portable Document Format files for viewers, parsers, upload tests.
seo_title: "Sample PDF files for testing — free, CC0, hotlinkable"
related: [docx, epub, edge]  # formats linked from this format's page
fixtures:
  - name: a4-3pages.pdf
    phase: 1
    generator: pdf.basic
    params: { pages: 3, page_size: A4, orientation: portrait, page_numbers: true }
    description: "A4 portrait, 3 pages of Lorem Ipsum body text with page numbers. Helvetica core font."
    tags: [document, multi-page, text]
    expect: { pages: 3, page_width_pt: 595.28, page_height_pt: 841.89, encrypted: false }
    size_class: free            # exact | boundary | approx | free
    nominal_bytes: null         # required for exact/boundary/approx
    mime: null                  # override, e.g. "text/plain; charset=utf-16"
    edge_case: false
    depends_on: []              # other fixture paths this generator reads (e.g. edge truncations, pdf-with-images)
    allow_large: false          # true permits bytes > MAX_FIXTURE_BYTES (never true in P1; needs an ADR)
    status: active              # active | removed
    removed: null               # for status: removed → { reason: "<text>", removed_at: "<RFC 3339>" }
    notes: null                 # free text carried into the manifest (e.g. determinism drift explanations)
    policy_exceptions: []       # e.g. ["mz-prefix"], ["decompression-ratio:2100"] — each must match a rule in validators/policy.py
    edge: null                  # for fixtures under edge/ → { intended_format: "pdf", defect: "truncated", source_fixture: "pdf/a4-3pages.pdf", fraction: 0.6 }  (fraction only for truncated; magic only for magic-prefix)
```

Field rules: `name`, `phase`, `generator`, `description`, `tags`, `size_class` are required; `expect` is required unless `edge_case: true`; `nominal_bytes` is required for `exact`/`boundary`/`approx`; `edge` is required for every fixture under `edge/` (its `defect` must be one of the closed enum in `04-manifest-and-discovery.md` §1.3, and `truncated` takes a `fraction`, `magic-prefix` a `magic` value); fixtures outside `edge/` may set `edge_case: true` without an `edge` block (they are valid files that are merely unusual, e.g. `txt/control-characters.txt`); `removed` is required when `status: removed`. Everything else is optional with the defaults shown. Generators declare `parallel_safe` themselves (see §4); it is not a catalog field.

Validation of the catalog itself (`tests/unit/test_catalog.py`): unique names, grammar (`03` §1 including the HLS exception), generator exists and accepts the params (signature check), `nominal_bytes` present when the size class needs it, `depends_on` acyclic and phase-consistent (a P1 fixture cannot depend on a P2 one), tags in vocabulary, description length.

## 4. Generator interface

```python
from loremfile.generators.base import GeneratorContext, generator

@generator(parallel_safe=True)          # default True; set False for memory-heavy generators (8000x8000 PNG, 100k-row datasets)
def basic(ctx: GeneratorContext, *, pages: int, page_size: str = "A4",
          orientation: str = "portrait", page_numbers: bool = False) -> bytes | pathlib.Path:
    ...
```

- `ctx` provides: `ctx.seed` (bytes = `sha256("loremfile:" + path)`), `ctx.rng` (`random.Random` seeded from `ctx.seed`), `ctx.path` (fixture path), `ctx.workdir` (temp dir), `ctx.dataset(name, n)` (see `05` §2), `ctx.dependency(path) -> bytes`, `ctx.tool("ffmpeg")` (absolute path in toolchain), `ctx.epoch` (SOURCE_DATE_EPOCH).
- **`ctx.dependency(path)` never regenerates a published fixture.** Resolution order: (1) `build/fixtures/<path>` if present in this build; (2) if `path` is in the committed manifest: download `BASE_URL + path`, verify `sha256` against the manifest, cache under `build/deps/`; (3) otherwise (the dependency is new in the same PR) generate it first (topological order). A hash mismatch in (2) aborts the build with an integrity error.
- Return `bytes` for small outputs or a `Path` to a file written in `ctx.workdir` for large ones. The framework moves it to `build/fixtures/<path>` and hashes it.
- Generators MUST NOT read wall-clock time, environment variables (other than through ctx), the network (`ctx.dependency` is the only sanctioned download), or locale. `util/determinism.py` **patches** the ambient sources of nondeterminism for the duration of a generator call rather than raising, because third-party libraries use them: `time.time`/`time.time_ns` return the epoch, `datetime.datetime.now/utcnow` return `2020-01-01T00:00:00Z`, `os.urandom`, `secrets.token_bytes`, `random.random` and friends, and `uuid.uuid4` draw from a SHAKE-256 stream seeded with `ctx.seed`; `locale` is forced to `C.UTF-8`; `TZ=UTC`; `PYTHONHASHSEED=0`. Generators themselves still use `ctx.rng` (a unit test greps generator modules for `random.` and `datetime.now` and fails on hits). The patches apply only inside `loremfile build`; `manifest update` and `verify-live` run unpatched and may use the clock (e.g. `generated_at`); `site build` runs unpatched too but deliberately uses the commit date instead of the clock so that its output is reproducible (`07` §4).
- **Library determinism claims.** Every row below is an *assumption about a third-party
  library's internals*, and only the run-twice test named in "Proving fixture" turns it
  into evidence. One of these was confirmed wrong (fastavro), which is why none of the
  unverified rows counts as evidence for the others. When a group is catalogued, spike
  its libraries first and correct this table in that group's own pull request.

  `tests/unit/test_determinism.py` parses this table and fails if a row marked verified
  has no proving fixture in its parametrisation, so a verified claim cannot sit here
  without a test behind it (docs/12 §2).

| Library | Claim | Proving fixture | Verified |
|---|---|---|---|
| fastavro | Sync marker is **not** reachable by the guard — `fastavro._write` is a compiled C extension — so it is passed explicitly as `sync_marker=ctx.stream(16)` | `avro/people-1000.avro` | 2026-09-07 (claim corrected) |
| avifenc | Invoked `--jobs 1 --speed 6`; multi-threaded AV1 makes timing-dependent choices | `avif/640x480.avif` | 2026-09-07 |
| fpdf2 | Encryption IV comes from the patched `os.urandom`; creation date, producer and creator set explicitly because fpdf2 formats the date itself | `pdf/a4-encrypted-1page.pdf` | 2026-09-08 |
| pyarrow | Parquet and Arrow are deterministic for a pinned version; the pandas metadata block is suppressed because it embeds a pandas version string | `parquet/people-1000.parquet` | 2026-09-07 |
| Pillow | `ImageFont.load_default(size)` and every save path are deterministic for a pinned Pillow | `png/640x480.png` | 2026-09-07 |
| SQLite | Fixed `page_size`, `journal_mode=DELETE` and a closing `VACUUM` make the page layout depend on contents, not insertion order | `sqlite/people-1000.sqlite` | 2026-09-07 |
| `util.zipnorm` | Sorted entries, fixed timestamps and permissions make any zip-based file byte-stable | `kmz/placemarks-10.kmz` | 2026-09-07 |
| **pyzipper** | AES salt/IV come from the patched `os.urandom` | `zip/aes256-password-loremfile.zip` | **unverified — spike in M3.7** |
| **py7zr** | Timestamps come from the patched clock | `7z/3-text-files.7z` | **unverified — spike in M3.7** |
| **cryptography** | X.509 serial fixed to `0x4c6f72656d66696c65`, subject/issuer `CN=fixture.example, O=loremfile fixtures`, SAN `fixture.example` (never the production hostname), validity 2020-01-01 to 2120-01-01, Ed25519 key from `sha256(b"loremfile:cert:ed25519")` and never written to disk | `pem/self-signed-ed25519-cert.pem` | **unverified — spike in M3.7** |
| mutagen | ID3v2.3 frames written with fixed values and no timestamps of any kind — `TDRC` is the catalog's literal year, not the build date, and no `TDEN`/`TDTG` is emitted. Cover art is a published PNG read through `ctx.dependency` | `mp3/with-id3v2-tags-3s.mp3` | 2026-09-09 (proving fixture corrected: the row named `sine-440hz-3s.mp3`, which carries no tags at all) |
| ffmpeg | `-fflags +bitexact -flags:v +bitexact -flags:a +bitexact -map_metadata -1` and an emptied encoder tag stop the version and build stamps reaching the container; `-threads 1` (and `-x264-params threads=1`, `-row-mt 0`) because multi-threaded x264 and VP9 both make timing-dependent slice decisions. Verified across all 14 encoder recipes M3.6 uses, in separate processes **and** in invocations minutes apart | `mp4/360p-5s.mp4` | 2026-09-09 |
| python-docx | Builds its package in memory, so every entry takes the patched clock. Core properties set explicitly, and the epoch value built at call time — inside the guard `datetime.datetime` is a stand-in class and python-docx type-checks its argument against whichever class is installed | `docx/1page.docx` | 2026-09-08 |
| openpyxl | **Not reproducible on its own.** It spools each worksheet to a temporary file and adds it with `ZipFile.write`, so that entry is stamped from the filesystem — beyond the reach of any clock patch. Raw output changed on six of eight consecutive runs while every other entry sat at the epoch. `util.zipnorm` is what makes it stable, so it is mandatory here, not cosmetic | `xlsx/1sheet-10rows.xlsx` | 2026-09-08 (claim corrected) |
| python-pptx | Builds its package in memory, like python-docx; core properties set explicitly. Slide size is set explicitly too — the bundled template is 4:3, which would otherwise be a silent default | `pptx/1slide.pptx` | 2026-09-08 |

  **Import these three libraries at module scope, never inside the guard.** They do
  `from datetime import datetime` at import time; imported inside `deterministic()` they
  bind the guard's stand-in class permanently and then reject real datetimes once it
  exits — openpyxl raised `TypeError: expected _FixedDatetime` inside the *validator*,
  in the same process, long after the generator had finished.

  If a library draws randomness below the Python layer and its run-twice test fails,
  pass an explicit IV, salt or marker where the API allows it — as fastavro now does —
  and otherwise move that fixture to P1b with a `notes` entry rather than publish
  nondeterministic bytes.

- Generators for zip-based formats (docx/xlsx/pptx/epub/kmz/zip) MUST pass their output through `util.zipnorm.normalize(bytes) -> bytes`: entries rewritten in sorted order (except EPUB's `mimetype` first and stored), all timestamps `1980-01-01 00:00:00` (zip minimum) — note this is the one place the fixed epoch is not 2020 because zip cannot represent it identically across libraries; `external_attr` fixed; UTF-8 flag set for non-ASCII names; deflate level 6; ZIP64 only when required.
- Office generators MUST also set document core properties (`created`, `modified`, `creator="loremfile.dev"`, `lastModifiedBy` same, `revision=1`) explicitly to the epoch, because `docProps/core.xml` is inside the zip.
- ffmpeg invocations MUST use `util.ffmpeg.run(...)`, which adds `-hide_banner -nostdin -y -threads 1 -map_metadata -1 -fflags +bitexact -flags:v +bitexact -flags:a +bitexact` and sets `-metadata encoder=`(empty) to strip the Lavf version string where the muxer allows it.
- Pillow: always `save(..., **fmt_opts)` without `exif` unless the fixture is about EXIF; never call `Image.open` on non-fixture inputs; use `ImageFont.load_default(size)` for labels (deterministic within the pinned Pillow).
- PDF (fpdf2): `pdf.set_creation_date(datetime(2020,1,1,tzinfo=timezone.utc))`, `pdf.set_producer("loremfile.dev")`, `pdf.set_creator("loremfile.dev")`; fpdf2 derives the file ID from content, so output is deterministic.
- pyarrow: pin version; Parquet `created_by` embeds the version string.
- SQLite: `PRAGMA page_size=4096; PRAGMA journal_mode=DELETE;` run `VACUUM` at the end; the header contains the SQLite library version so the toolchain must be pinned.
- Fonts (fontTools): set `head.created`/`head.modified` to the epoch explicitly.

## 5. Dependency resolution and build order

`loremfile build` resolves `depends_on` into a DAG and generates in topological order, parallelising independent fixtures across `-j N` workers (default `os.cpu_count()`); generators marked `parallel_safe=False` run alone. Dataset generation runs once per process and is cached in memory.

**As implemented in M3.1, generation is sequential and `-j` is not yet accepted.** The determinism guard patches process-global state — `os.urandom`, the clock, the `random` module — so two generators cannot run concurrently *in one process* without corrupting each other's stream; threads are therefore not an option and the parallel path has to be process-based. It is deferred to **M3.6**, where media encoding makes wall-clock time actually matter and separate processes make the patches safe again. The M3.1 set (43 fixtures, 243 MB) builds in about 8 seconds, so there is nothing to gain before then.

**What gets generated (selection rule):**

| Invocation | Selection |
|---|---|
| `loremfile build --new` (CI on a pull request) | Catalog fixtures whose `path` is **absent from the merge-base manifest** (`git show origin/main:manifest.json`), plus their not-yet-published dependencies. The PR is expected to already contain the matching manifest entries (the author ran `manifest update` locally); `manifest check` then verifies them against the regenerated bytes. |
| `loremfile build --missing-in-bucket` (deploy on `main`) | Active manifest entries whose key is **absent from the bucket** (one `ListObjectsV2` pass, compared by key and by the `sha256` object metadata). Regenerated bytes must equal the committed manifest hashes or the deploy fails. The manifest is never rewritten during deploy. |
| `loremfile build --all [--audit]` (monthly audit, restore) | Every active fixture; `--audit` reports drift instead of failing. |
| `--only <path…>` / `--format <fmt…>` / `--group <media\|data\|other>` / `--phase N` | Filters applied on top of the selection above (or, if none of the three modes is given, on the whole catalog). Groups: `media` = mp4 webm mkv mov avi ogv ts hls mp3 wav flac ogg opus m4a aac aiff; `data` = csv tsv json ndjson xml yaml toml ini parquet avro arrow sqlite sql geojson gpx kml kmz; `other` = everything else. |

**A build that selects nothing is a success, and `validate` has to be able to tell.** Every `build` writes `build/selection.json` — the selection mode, the filters and the paths it chose — beside `build/fixtures/`, not inside it, because everything inside is publishable. `validate` then reads it:

| `build/selection.json` | `build/fixtures/` | `validate` |
|---|---|---|
| absent | empty | **error** — no build ran here |
| present, selected nothing | empty | **ok**, `validated=0` — a pull request that touches no catalog entry, which is what every infrastructure-only change looks like |
| present, selected *N* | missing some of them | **error**, naming each — a build that half-failed, whatever its exit code said |

Without the receipt those three cases are one empty directory. The first version of this check had only the directory to go on, so it failed `ci.yml` on the M0 infrastructure pull request, which correctly built nothing.

## 6. Validators

For each generated file, `validators.validate(path, catalog_entry) -> props`:

1. **Magic bytes / structure** against the expected format (table in `validators/__init__.py`: PDF `%PDF-`, PNG signature, JPEG `FFD8FF`, GIF `GIF8`, WebP `RIFF….WEBP`, AVIF `ftypavif`, MP4 `ftyp`, WebM/MKV `1A45DFA3`, MP3 `ID3` or frame sync, WAV `RIFF….WAVE`, FLAC `fLaC`, OGG `OggS`, ZIP `PK\x03\x04` (or `PK\x05\x06` for empty), 7z `7z\xBC\xAF\x27\x1C`, gzip `1F8B`, bz2 `BZh`, xz `FD377A585A00`, zstd `28B52FFD`, Parquet `PAR1` head and tail, SQLite `SQLite format 3\0`, WOFF `wOFF`, WOFF2 `wOF2`, TTF `\0\1\0\0`, OTF `OTTO`, wasm `\0asm`, EPUB = zip with `mimetype` entry first). Edge fixtures declare `intended_format` and the check is inverted/skipped per `defect`.
2. **Parse with an independent reader** and measure props: pypdf + `qpdf --check` (pdf); Pillow `verify()` + reopen (images); `ffprobe -show_streams -show_format` (media); python-docx/openpyxl/python-pptx reopen (office); `csv` module with the delimiter taken from the catalog entry rather than sniffed — a fixture declares its delimiter, and `Sniffer` can guess wrong on exactly the awkward files these fixtures exist to be (corrected in M3.2a) — plus a `chardet`-free explicit decode (text: decode with the declared charset strictly; count lines and detect line endings by bytes); `json.loads` / `ijson` for large; `lxml` with `resolve_entities=False, no_network=True` (xml); `pyarrow.parquet.read_metadata` / `fastavro.reader` / `pyarrow.ipc`; `sqlite3` `PRAGMA integrity_check` == `ok`; `zipfile.testzip()` is `None`, `tarfile` walk, `py7zr.test()`; fontTools `TTFont` load + glyph count; `email` package parse; `icalendar` / `vobject` parse; `cryptography.x509` load; `wasmtime`? — no: a minimal hand-written wasm parser checks sections (keep the toolchain small).
3. **Expectations**: every key in `expect` must equal the measured prop (floats within 0.01).
4. **Size class**: `exact` ⇒ `bytes == nominal_bytes`; `boundary` ⇒ `bytes == nominal_bytes ± 1` as named; `approx` ⇒ within ±5 %; `free` ⇒ `bytes ≤ MAX_FIXTURE_BYTES`.
5. **Policy scan** (`validators/policy.py`): reject if bytes contain `-----BEGIN` + `PRIVATE KEY`, the EICAR test string, `MZ` at offset 0, ELF/Mach-O magic, `<!ENTITY` with `SYSTEM`/`PUBLIC` (external entities), in SVG: `<script`, `on[a-z]+=` attributes, `javascript:` URLs, `<foreignObject`, `<set`/`<animate` targeting `href`, external `href`/`xlink:href` schemes; in HTML: `on[a-z]+=` attributes and `javascript:` URLs (exception: `html/with-inline-js.html` may contain one `<script>` with `console.log` only, declared as `policy_exceptions: [inline-script-console]`); `/JavaScript` or `/JS` or `/Launch` or `/OpenAction` in PDF, macros in OOXML (`vbaProject.bin`), archive decompression ratio > 1000:1. Exceptions are declared **by path** in the catalog's `policy_exceptions` (`mz-prefix` for `edge/exe-header-with-txt-extension.txt`; `decompression-ratio:<n>` for `zip/zip64-70000-empty-files.zip` with the measured ratio); the manifest records the resulting hash so the exception is auditable.
6. **Text hygiene**: every `text/*`, `application/json`, `application/xml`, `application/yaml`, `application/toml`, `application/x-ndjson`, `application/geo+json` fixture carries an explicit charset in its `mime` (`; charset=utf-8` by default — the catalog loader appends it when absent; per-fixture overrides for `iso-8859-1`, `windows-1252`, `shift_jis`, `gb2312`, `utf-16`, `utf-32` are listed in `05` §1 rule 7) and the bytes must decode strictly with that charset. Edge fixtures with `defect: invalid-encoding` are exempt.

Validation failures are hard errors in CI and print a table of path → failed check.

## 7. Manifest and lock check

`loremfile manifest update`:

1. Load committed `manifest.json` (may be empty on first run).
2. For each generated fixture, compute `sha256`, `bytes`, props; build the entry.
3. **Lock rule**: if `path` already exists in the committed manifest, then `sha256`, `bytes` and `mime` MUST be identical. `props` are compared only when the bytes were regenerated in this run and differ from the manifest — identical bytes with different measured `props` (a validator library measuring a field differently after an upgrade) produce a warning and keep the committed props, which describe the published bytes. `description`, `tags`, `notes`, `deprecated`, `supersededBy`, `generator` and `generator_params` MAY change. Any violation fails with a diff.
4. **Removal rule**: a path present in the committed manifest but absent from the catalog fails, unless the catalog marks it `status: removed` with `removed.reason` and `removed.removed_at`; the manifest entry becomes a tombstone (`04` §1.5) — the catalog's nested `removed.reason`/`removed.removed_at` map to the tombstone's top-level `reason`/`removed_at`.
5. **Top-level metadata**: `generated_at` is set to the current UTC time only when the fixture list or any entry changed; `toolchain_image` is set from `tools/TOOLCHAIN_DIGEST`. Both are excluded from the lock comparison, so a digest-bump PR runs `manifest update` and commits the two-line change.
6. Write `manifest.json` (sorted by path, 2-space indent, LF, trailing newline, `ensure_ascii=False`), `sha256sums.txt` and `formats.json`. (Per-format `index.json` files are written by `site build`, the single owner of `build/site/`.)
7. Enforce `MAX_TOTAL_BYTES`.

`loremfile manifest check` performs steps 1–5 and 7 without writing and additionally verifies, for every fixture generated in this run, that the committed entry's `sha256`/`bytes`/`mime`/`props` equal the regenerated values (used by CI on PRs and by deploy). `manifest update` is only ever run by a human or agent inside the toolchain container while preparing a PR; `AGENTS.md` forbids hand-editing the file.

## 8. Determinism audit

`loremfile build --all --audit` regenerates **every** fixture including published ones (dependencies still come from published bytes, §4) and compares hashes with the manifest. Output: a Markdown report listing drifted paths with generator names. Run monthly by `audit.yml`; drift is a warning that opens a `determinism` issue, never a deploy blocker (published bytes are canonical; the generator gets fixed or the drift is documented in `notes`).

## 9. Toolchain container (`tools/Dockerfile`)

```dockerfile
FROM python:3.12-slim-bookworm@sha256:782412e8…  # pinned by index digest; Dependabot bumps it
ENV DEBIAN_FRONTEND=noninteractive TZ=UTC LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONHASHSEED=0 SOURCE_DATE_EPOCH=1577836800
RUN apt-get update && apt-get install -y --no-install-recommends \
      git=<ver> gh=<ver> ca-certificates=<ver> curl=<ver> \
      ffmpeg=<ver> qpdf=<ver> libavif-bin=<ver> zstd=<ver> xz-utils=<ver> bzip2=<ver> sqlite3=<ver> fonts-dejavu-core=<ver> \
    && rm -rf /var/lib/apt/lists/*
# Every apt package is pinned to the exact version recorded in tools/apt-versions.txt (first build: install unpinned, run `dpkg -l`, then pin). Recorded in M1.2 — that file is the single source of truth; the real Dockerfile carries the literal versions.
# Pinned versions disappear from the Debian mirrors after point releases; when that happens, point the sources at snapshot.debian.org for the recorded date.
# git and gh are required because every workflow job runs inside this image: actions/checkout needs git for a real clone,
# `build --new` reads origin/main:manifest.json, check_lock.sh diffs against the merge-base, gh_issue.py and release.py call gh.
# gh comes from GitHub's apt repository (https://cli.github.com/packages) — add its key and source before apt-get, pinned to a version.
COPY tools/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
WORKDIR /work
```

- `tools/requirements.in` lists direct deps with minimum versions where a feature depends on it: `fpdf2>=2.8`, `pypdf>=5`, `Pillow>=11.3` (AVIF support in wheels starts at 11.3.0), `python-docx>=1.2` (comments API), `openpyxl`, `python-pptx`, `pyarrow>=17`, `fastavro`, `py7zr`, `pyzipper`, `zstandard`, `fonttools[woff]`, `brotli`, `mutagen`, `lxml`, `PyYAML`, `tomli-w`, `jsonschema`, `pydantic>=2`, `click`, `Jinja2`, `boto3`, `requests`, `icalendar`, `vobject`, `cryptography`, `markdown-it-py`, `ijson`, `html5lib`, `pytest`, `responses`, `ruff`, `mypy` plus stub packages (`types-requests`, `types-PyYAML`, `boto3-stubs[s3]`), `pip-tools`. `tools/requirements.lock` is produced by `pip-compile --generate-hashes` and pinned exactly. EPUB files are built with the standard library `zipfile` (no EPUB library); DOCX table-of-contents fields are inserted as raw `w:fldSimple` XML because python-docx has no TOC API.
- Tools that run on the host, not in the image: `actionlint` (workflow lint), `gitleaks` (secret scan), Lighthouse (`npx lighthouse https://loremfile.dev/ --only-categories=accessibility,performance,seo --preset=desktop`) — all informational except gitleaks, which must be clean once in M1.8.
- `fonts-dejavu-core` is installed **only** for rendering label text inside images/PDF test cards where Pillow's default font is too small; it is a Debian package under the Bitstream Vera licence, which permits embedding and redistribution. The generated font family is not derived from it.
- The image is built and pushed to `ghcr.io/<OWNER>/loremfile-toolchain` by `toolchain.yml`; workflows reference it by `@sha256:` digest recorded in `tools/TOOLCHAIN_DIGEST`. Changing the digest is a reviewed PR.
- **Verified in M1.2 on 2026-09-07** (linux/amd64, `python:3.12-slim-bookworm@sha256:782412e8…` = python 3.12.14 on Debian 12.15, ffmpeg `7:5.1.9-0+deb12u1`). `ffmpeg -encoders` lists every P1 encoder — `libx264`, `libvpx` (VP8), `libvpx-vp9`, `libopus`, `libvorbis`, `libmp3lame`, `aac` (native), `flac`, `libtheora`, `prores_ks` — and **also `libx265` and `libsvtav1`**, so the P2 HEVC/AV1 fixtures need no rebuild of the image. Two naming details the generators must use: the Theora encoder is **`libtheora`**, not `theora`; ProRes ships as three encoders (`prores`, `prores_aw`, `prores_ks`) and the catalog means **`prores_ks`**. AVIF is produced with `avifenc` from `libavif-bin` 0.11.1 (aom 3.6.0 encoder, dav1d 1.0.0 decoder), not through ffmpeg.
- **Verified in M1.2 on 2026-09-07**: the image's SQLite is 3.40.1 and `sqlite3 :memory: "PRAGMA compile_options;"` lists `ENABLE_FTS5` (also FTS3/FTS4). `.tar.zst` is produced by piping through the `zstandard` Python package: the image's Python 3.12.14 raises `CompressionError: unknown compression type 'zst'` for `tarfile.open(..., "w:zst")` and has no `compression.zstd` module.
- `tools/TOOLCHAIN_DIGEST` contains exactly one line: the full image reference `ghcr.io/<OWNER>/loremfile-toolchain@sha256:<64 hex>`; workflows and `docker pull` read it verbatim.

## 10. CLI

| Command | Purpose |
|---|---|
| `loremfile catalog validate` | Schema + cross checks on `catalog/*.yaml` |
| `loremfile build (--new \| --missing-in-bucket \| --all) [--audit] [--only path…] [--format fmt…] [--group media\|data\|other] [--phase N] [-j N]` | Generate to `build/fixtures/` per the selection rule in §5 |
| `loremfile validate [--only path…] [--format fmt…]` | Run validators on `build/fixtures/` |
| `loremfile manifest update|check` | §7 |
| `loremfile site build` | Render site to `build/site/` (see `07-website.md`) |
| `loremfile site serve [--port 8080]` | Preview `build/site/` with production-like routing (extensionless keys as `text/html`, `/` → `index.html`, trailing slash → `index.html`) |
| `loremfile upload [--fixtures] [--site] [--dry-run] [--force-site] [--from-dir <dir>] [--restore <archive> [--only path…]]` | See `09-ci-cd.md` §5. `--from-dir` uploads a prepared directory (restore drill); `--restore` uploads from a release archive only where the live object is missing or its hash differs from the manifest |
| `loremfile upload --apply-removals` | Deletes objects whose manifest entry is `status: removed` and purges their URLs; the only delete path in the tool besides `probe --down` (takedown flow, `11` §7.8; the owner must have lifted the prefix's bucket lock first) |
| `loremfile probe (--up \| --check \| --down)` | Uploads the M2.4 probe objects under `_probe/`, runs the behavioural checks, deletes them; deletes are restricted to the `_probe/` prefix. `--check` also writes `_locktest/probe` once (a locked prefix, `08` §7b) and verifies that overwriting and deleting it are refused |
| `loremfile purge --site` | Purge site/discovery URLs from the Cloudflare cache |
| `loremfile verify-live [--mode smoke\|daily\|full] [--inject-failure path]` | Contract checks against production; `--inject-failure` reports the given path as failing to exercise the issue automation (REQ-27) |
| `loremfile infra apply [--dry-run]\|audit [--strict]` | See `08-infrastructure.md`; `apply --dry-run` prints the plan; `audit` warns on unreadable settings and fails only with `--strict` |
| `loremfile tokens-due [--json]` | Reads `infra/token-expiry.json` and lists tokens expiring within 30 days (health.yml `rotation-due` step) |
| `loremfile infra locks --write` | Regenerates `infra/r2-locks.json` (one indefinite lock rule per format prefix) from the catalog |
| `loremfile infra allowlist-rule` | Prints the WAF custom-rule expression that blocks paths outside known prefixes (incident use, `11` §7.4) |
| `loremfile usage [--json]` | Reads R2 operations month-to-date and zone traffic via GraphQL Analytics with the read-only token (health/cost step) |
| `loremfile release redact --path <path>` | Rebuilds and re-uploads every release asset containing the path without it (`09` §10) |
| `loremfile release archive (--since <tag> \| --snapshot)` | Build the delta or full snapshot archive(s) for a GitHub Release (`09` §3.5) |

All commands exit non-zero on any failure. With `--json` every command prints one object: `{"command": str, "ok": bool, "summary": {<counts>}, "items": [{"path": str, "status": str, "detail": str}], "errors": [str]}`; `verify-live` items use `status ∈ {ok, missing_object, content_length_mismatch, content_type_mismatch, hash_mismatch, header_missing, status, timeout, rdap_expiry, tls_expiry, security_txt_expiry}`.

## 11. Local development

```bash
git clone https://github.com/<OWNER>/loremfile && cd loremfile
docker pull $(cat tools/TOOLCHAIN_DIGEST)
docker run --rm -it -v "$PWD:/work" $(cat tools/TOOLCHAIN_DIGEST) bash
pip install -e .
loremfile catalog validate
loremfile build --only pdf/a4-3pages.pdf
loremfile validate --only pdf/a4-3pages.pdf
loremfile manifest update            # adds the new entry; commit manifest.json + sha256sums.txt in your PR
loremfile site build && loremfile site serve   # http://localhost:8080 with production-like routing
```

Without Docker, most text/data/image/office generators run on a plain Python 3.12 with the lock file; media generators need ffmpeg on `PATH` and the results will differ from the pinned image (the lock check will tell you). Only Docker output is authoritative.

## 12. Performance budget

| Step | Budget (GitHub-hosted ubuntu runner, 4 vCPU) |
|---|---|
| Full phase-1 generation (≈ 416 files, ≈ 0.96 GB; the 228-file launch set is ≈ 515 MB of it) | ≤ 25 min (video ≈ 12 min, audio ≈ 3 min, data ≈ 4 min, rest ≈ 3 min) |
| Validation | ≤ 5 min |
| Incremental PR build (typical: < 10 new fixtures) | ≤ 5 min |
| Site build | ≤ 30 s |
| Upload (≈ 515 MB launch set, first time) | ≤ 10 min (multipart, 16 MiB parts, 8 threads) |

If the full build exceeds budget, split video generation into a matrix job (see `09` §3.1) before trimming scope.

## 13. Coding standards

- Python 3.12, type hints everywhere, `ruff` (lint + format) with the config in `pyproject.toml`; `mypy --strict` on `src/`.
- No global state; generators are pure functions of `(ctx, params)`.
- Every generator has a unit test that runs it twice and asserts identical bytes (`tests/unit/test_determinism.py` parametrised over the catalog, phase 1, with small params where the catalog params would be slow).
- Every validator has a negative test (a corrupted input must fail).
- **Validators assert structure, not merely parseability.** A fixture that parses but is
  semantically wrong is worse than one that fails to parse, because it ships and looks
  correct. The standard set in M3.2b: the GeoJSON validator range-checks every position,
  so a file with latitude and longitude swapped is rejected rather than accepted as
  valid JSON; the SQLite multi-table fixture is checked for orphaned foreign keys, so a
  relational example that does not actually relate cannot be published. Ask what a
  *plausible but wrong* file would look like in this format, and assert against that.
- Docstrings state the exact output properties the generator guarantees.
