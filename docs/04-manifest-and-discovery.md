# 04 — Manifest and Discovery Files

## 1. `manifest.json` (stable, schema-versioned)

Location: repository root (committed) and `https://loremfile.dev/manifest.json` (deployed copy, identical bytes).

### 1.1 Top-level object

```json
{
  "$schema": "https://loremfile.dev/schema/manifest-v1.json",
  "schema_version": 1,
  "catalog_version": "1.0.0",
  "generated_at": "2026-10-01T12:00:00Z",
  "base_url": "https://loremfile.dev/",
  "license": "CC0-1.0",
  "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
  "source": "https://github.com/kumarprabhashanand/loremfile",
  "toolchain_image": "ghcr.io/kumarprabhashanand/loremfile-toolchain@sha256:<digest>",
  "count": 416,
  "total_bytes": 1060000000,
  "formats": ["avif", "bin", "csv", "..."],
  "fixtures": [ { "...": "see 1.2" } ]
}
```

`count` and `total_bytes` count every entry, the `sample.{format}` aliases included (at 1.15.1, 409 entries, 75 of them aliases, against the 334 files the site counts), and `total_bytes` includes the duplicated bytes because R2 stores each alias as an object of its own. Subtract the entries whose `generator` is `alias.copy` for the site's figures.

### 1.2 Fixture entry

```json
{
  "path": "pdf/a4-3pages.pdf",
  "url": "https://loremfile.dev/pdf/a4-3pages.pdf",
  "format": "pdf",
  "ext": "pdf",
  "mime": "application/pdf",
  "bytes": 12345,
  "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "size_class": "free",
  "phase": 1,
  "description": "A4 portrait, 3 pages of Lorem Ipsum body text with page numbers. Helvetica core font, no embedded fonts.",
  "tags": ["document", "multi-page", "text"],
  "edge_case": false,
  "props": { "pages": 3, "page_width_pt": 595.28, "page_height_pt": 841.89, "encrypted": false, "pdf_version": "1.7" },
  "generator": "pdf.basic",
  "generator_params": { "pages": 3, "page_size": "A4", "orientation": "portrait", "page_numbers": true },
  "added_in": "1.0.0",
  "status": "active",
  "deprecated": false,
  "supersededBy": null,
  "notes": null
}
```

Field rules:

| Field | Type | Rule |
|---|---|---|
| `path` | string | Unique. Matches URL grammar in `03-http-contract.md` §1. Does not change. |
| `url` | string | `base_url + path`. |
| `format` | string | First path segment. |
| `ext` | string | Everything after the first dot of the **last path segment** (`tar.gz`, not `gz`; `m3u8` for `hls/720p-10s/index.m3u8`). |
| `mime` | string | Exact `Content-Type` served. From the format's default in the catalog unless overridden per fixture (e.g. charset). |
| `bytes` | integer | Exact size. Frozen. |
| `sha256` | hex string (64) | Frozen. |
| `size_class` | enum | `exact` (bytes equal nominal), `boundary` (nominal ± 1 exactly), `approx` (within ±5 % of nominal), `free` (no size claim in name). |
| `phase` | integer | 1–4. |
| `description` | string | One or two sentences a human or agent can use to decide fit. ≤ 300 chars. |
| `tags` | string[] | Lowercase; controlled vocabulary in `catalog/_tags.yaml`. |
| `edge_case` | boolean | `true` for anything under `edge/` and for format-dir fixtures flagged as unusual (e.g. `txt/control-characters.txt`). |
| `props` | object | Measured by validators, format-specific (see §1.3). The measured *values* cannot change, because the bytes they were measured on cannot: `sha256` is frozen, so `pages` or `rows` is settled for good. What a prop is called, and the wording of one that is a sentence, may be corrected: a correction is a changelog entry and a new catalog version, never a silent rewrite. |
| `generator`, `generator_params` | string, object | Enough to regenerate. Informational; may change if a generator is refactored (bytes must not). |
| `added_in` | semver | Catalog version that introduced it. |
| `status` | enum | `active`, `removed` (legal takedown tombstone, see §1.5). |
| `deprecated`, `supersededBy` | boolean, string/null | Derived, never set here: the catalog's `superseded_by` is the input, and `manifest update` writes both fields from it (`03` §7.3), so a value set by hand in the manifest is overwritten by the next update and `manifest check` reports it until then. `supersededBy` is the replacing path. A superseded entry stays active and served, and stays in `manifest.json`, `sha256sums.txt` and `{format}/index.json`; format pages, the search index and `llms-full.txt` list its replacement instead. |
| `generator`, `generator_params.of` | string, string | How an alias says what it is (since 1.15.0), with no field of its own: a `sample.{format}` alias is an entry whose `generator` is `alias.copy`, and its original is the `of` in its `generator_params`. Its `sha256`, `bytes`, `mime` and `props` equal the original's, and a test holds that. An alias is not a second file: the site's counts, format pages, `search-index.json`, `llms-full.txt`, `formats.json` and `{format}/index.json` leave it out, and `manifest.json` and `sha256sums.txt` carry it. The clients skip aliases when they list or select by format, and `--include-aliases` brings them back; a path named outright is always fetched. `catalog/_aliases.yaml` lists them; `05` §8 gives the rule and the table. 1.15.0 briefly wrote a field `aliasOf`, which the published schema does not allow: see §1.4. |

### 1.3 `props` by format (what validators measure)

| Formats | Keys |
|---|---|
| pdf | `pages`, `page_width_pt`, `page_height_pt`, `encrypted`, `pdf_version`, `has_outline`, `has_images`, and for a PDF with an AcroForm only, `form_fields` and `filled_fields` (a filled field must carry its appearance stream). Since 1.12.0, each of these appears only on a file that has what it measures: `outline_entries` and `outline_pages` (the page each bookmark opens, 1-based; a bookmark that opens no page is refused), `internal_links`, `external_links` and `link_uris` (an internal link must land on a page of the file), `page_sizes` (every page's box, when they differ), `page_rotations` (each page's `/Rotate`, when any is not 0), and `latin1_characters` for a file whose catalog row sets `accents` |
| png, jpg, gif, webp, avif, bmp, tiff, ico | `width`, `height`, `mode` (`RGB`, `RGBA`, `L`, `P`, `CMYK`, `I;16`, `I;16B`), `frames`, `animated`, `progressive`, `exif_orientation` (jpg), `sizes` (ico); for tiff (1.9.0), `compression` as Pillow names it (`raw`, `tiff_lzw`), `byte_order` (`II` or `MM`, the header's first two bytes) and `bits_per_sample` (one value per sample, from tag 258). Since 1.13.0, each of these appears only on a file that has what it measures: `interlaced` (png, when IHDR's interlace method is Adam7), `palette_entries` (png of mode `P`: the entries in its PLTE chunk), `transparent_pixels` (an indexed image with a transparent palette index: the pixels that use it), `gps_latitude` and `gps_longitude` (jpg, signed decimal degrees from the EXIF GPS block, which must name both) and `exif_datetime_original`. A declared JPEG `quality` or WebP lossless switch is checked against the bytes (the quantization tables; VP8 against VP8L chunks) and not reported, because published rows declare them |
| heic | `width` and `height` (the primary item's `ispe`, which heif-convert's decode must match), `mode` (decoded), `major_brand`, `compatible_brands`, `primary_item_type` (`hvc1`), `items`, `format` |
| svg | `width`, `height` and `viewbox` (each `null` when the attribute is absent), `root_element`, `has_dtd`, `elements` and the text keys; since 1.13.0, only where present, `gradients`, and `symbols`, `symbol_viewboxes` and `uses` (every `use` and every `url(#id)` must name an id the file holds) |
| mp4, webm, mkv, mov, avi, ogv, ts, hls | `duration_ms`, `width`, `height`, `fps`, `vcodec`, `acodec`, `sample_rate`, `channels`, `video_streams`, `audio_streams`, `subtitle_streams`, `profile` (the video stream's profile as ffprobe names it, where it reports one: `High`, `Constrained Baseline`, `Profile 0`), and for H.264 `level` (`3.0`, `3.1`: the stream's level_idc over ten); mp4 and mov where the catalog sets `faststart`: `faststart`, `moov_at_end`. Since 1.14.0, two keys appear only on a file that has what they measure, so no other entry changes: `rotation` (the clockwise turn in degrees that the video track's display matrix asks of a player, `90` for a portrait video stored landscape; ffprobe reports the matrix counterclockwise, and the key turns the sign) and, for a webm or mkv stream whose container flags an alpha plane (Matroska's AlphaMode), `alpha` (`true`), `alpha_min` and `alpha_max` (the extremes of the plane decoded from the first frame, 0 to 255, so a flagged stream that is fully opaque reads `alpha_min` 255). hls media playlists: `segments`, `target_duration_s`, `playlist_type`; hls master playlists: `variants`, and per rendition in order `bandwidths`, `resolutions` and `codecs` (a validator reads them from the playlist; a CI test re-measures each from the rendition's segments); Since 1.9.1, every file with an audio stream (HLS segments too) carries `tone_hz`: one value per channel, in Hz to a tenth, measured by Goertzel over one decoded second from 0.25 s at 8 kHz (`util/tone.py`), `null` for a channel where no single frequency holds 0.9 of the energy, and no key at all when no channel has a tone (`mp3/silence-5s.mp3`). A chained Ogg file decodes as its first chain, so it adds `chain_tone_hz`, one such list per chain, each measured from that chain's own bytes. Since 1.10.0, three keys appear only on a file that has what they measure, so no other entry changes: `track_tone_hz` (one `tone_hz` list per audio track, when there is more than one), `scodec` (the first subtitle track's codec: `subrip` for SRT) and `chapters` (how many chapters ffprobe reports). |
| mp3, wav, flac, ogg, opus, m4a, aac, aiff | `duration_ms`, `acodec`, `sample_rate`, `channels`, `audio_streams`, `bitrate_kbps` (the audio packets' bytes over the stream's duration: what the codec spent, without container pages, tags or cover art, and never the rate an encoder was asked for or a header declares), `bit_depth` (PCM only); wav also `header_format` (`pcm`, `extensible` or `float`, the `fmt ` chunk's tag) and `header_bytes` (where the samples start: 44 for the canonical header, 68 for the extensible one, 58 for the float header with its `fact` chunk, and later whenever another chunk comes first, as 94 does in `wav/with-list-chunk-3s.wav`), and since 1.10.0 `info_tags` when a LIST/INFO chunk precedes the samples, each tag by its four-character id; for ogg (1.9.0), `chains` and `header_pages` from the Ogg pages themselves, a chained file's `duration_ms` and `bitrate_kbps` summed over its chains (ffprobe reports the first chain alone), and for Vorbis its comments as `tags` and its cover as `cover` (`format`, `width`, `height`, decoded with Pillow); Since 1.9.1, every file with an audio stream (HLS segments too) carries `tone_hz`: one value per channel, in Hz to a tenth, measured by Goertzel over one decoded second from 0.25 s at 8 kHz (`util/tone.py`), `null` for a channel where no single frequency holds 0.9 of the energy, and no key at all when no channel has a tone (`mp3/silence-5s.mp3`). A chained Ogg file decodes as its first chain, so it adds `chain_tone_hz`, one such list per chain, each measured from that chain's own bytes. |
| docx | `paragraphs`, `tables`, `table_rows`, `images` (media parts), `words`, `inline_images`, `anchored_images` (floating drawings, which readers that walk inline shapes miss), `images_with_alt_text`; the tracked-changes file adds its revision props; since 1.12.0, each only on a document that has what it measures: `page_breaks` (forced breaks) and `min_pages` (one more than the breaks: a .docx stores no page count of its own), `headers` and `footers` with `header_text`, `footer_text` and `footer_fields`, `headings`, `toc_fields`, `toc_entries` and `update_fields_on_open` (each cached contents entry must name its heading, at its level and on its page), `comments` and `comment_authors` (the comment wiring is checked as for tracked changes), `scripts` (when there is more than one, as Unicode names them) and `rtl_paragraphs` |
| xlsx | `sheets`, `sheet_names`, `rows` and `columns` (first sheet, rows incl. header), `formulas` (every sheet; each must carry a cached value), `images`, and `cross_sheet_formulas` only where a formula reads another sheet; since 1.12.0, `merged_ranges` and `merged` (first sheet), `auto_filter` and `freeze_panes` (first sheet, only with a filter), `charts`, `chart_series` and `chart_types` (every series must read cells that exist and hold values), and for `xlsx/unicode-strings.xlsx` `scripts` and `rtl_cells` |
| pptx | `slides`, `layouts`, `images`, `slide_width_emu` and `slide_height_emu` (16:9 is 12191695 by 6858000, 4:3 is 9144000 by 6858000), `notes` (slides with speaker notes); since 1.10.0 `tables` and `charts` (native shapes, not pictures of them) and `hidden_slides` (slides marked `show="0"`) |
| txt, md, html, css, js, rtf, srt, vtt, log, sql, ini | `encoding`, `bom`, `line_ending` (`lf`/`crlf`/`cr`/`mixed`/`none`), `lines`, `max_line_bytes`; md also `headings`, `anchor_links` (in-page links, every one resolving to a heading's anchor) and `footnotes` (every reference with a body and every body referenced); rtf also, since 1.12.0 and only where there is any, `table_rows` and `table_columns` (every row must have as many cells as cell edges), `has_color_table`, and `bold_spans`, `italic_spans`, `underline_spans` and `colored_spans` (a colour or font the document names must be in its table) |
| csv, tsv | plus `rows` (data rows), `columns`, `delimiter`, `has_header`, `quoted_fields`, and the two causes of quoting reported apart: `quoted_delimiter` (a field holds the delimiter) and `quoted_newline` (a field holds a line break) |
| json, ndjson, geojson, har, ipynb, jsonld | `top_type` (`object`/`array`/`string`…), `items` (array length or ndjson lines), `max_depth` |
| xml, rss, atom, kml, gpx | `root_element`, `encoding`, `has_dtd`, `namespaces` |
| yaml, toml | `documents` (yaml), `top_keys` |
| parquet, avro, arrow | `rows`, `columns` (for parquet the leaf columns, as Parquet counts them), `compression` (parquet), `row_groups`; since 1.10.0 parquet also `column_types` (each top-level column's Arrow type, as pyarrow spells it); for arrow (1.9.0), `ipc_format` (`file` when the bytes start and end with `ARROW1`, else `stream`, and held to the served type), `compression` (`zstd`, `lz4` or `none`, from the codec frame's magic, which pyarrow never reports), `column_types` and `null_counts` |
| sqlite | `tables`, `rows_total`, `page_size`, `journal_mode`, `has_fts` |
| zip, 7z | `entries`, `directories`, `method` (`stored`/`deflate`/`lzma2`), `encrypted`, `zip64`, `comment` |
| tar (+gz/bz2/xz/zst) | `entries`, `compression`, `has_symlinks`, `pax` |
| gz, bz2, xz, zst | `members` (gz), `original_bytes` |
| ttf, otf, woff, woff2 | `glyphs`, `flavor`, `family_name`, `units_per_em` |
| bin | `pattern` (`shake256`, `zeros`, `ones`, `incrementing`) |
| ics | `events`, `has_vtimezone`, `has_rrule` |
| vcf | `cards`, `version` |
| eml, mbox | `messages`, `parts`, `attachments`, `has_html` |
| epub | `epub_version` (`3.0` or `2.0`), `chapters`, `documents` (XHTML parts), `has_nav` (EPUB 3's navigation document); since 1.12.0 `has_ncx` (EPUB 2 only: the spine names an NCX whose uid is the book's identifier) and `images` (image items in the manifest, every `<img>` resolving to one and carrying alt text); every manifest item must be in the book and every spine item in the manifest |
| pdf, docx, pptx, xlsx, epub, html, md | `contains_text` on the fixtures §1.3.2 names: three to five strings a correct reader finds in the file |
| pem, der | `kind` (`certificate`/`csr`), `algorithm`, `not_before`, `not_after` |
| wasm | `sections`, `exports` |
| edge/* | `defect`, `intended_format`, `bytes`, `damage`, `outcome`, `compare_with`, and `derived_from` for the six that were cut or copied from a published fixture; plus `fraction` (truncated) and `hostile_entries` (hostile-name). §1.3.1 describes the four that are about the breakage. `defect` is a closed enum, and it tells the validator what to assert: `zero-byte` (bytes == 0), `truncated` (bytes == floor(`fraction` × source bytes) with `fraction` from the catalog's `edge` block, default 0.5 (`pdf-truncated-60pct.pdf` uses 0.6), and prefix-equal to the source), `mismatched-extension` (bytes equal the source fixture; magic bytes match the *source* format, not the extension), `magic-prefix` (bytes == the `magic` value from the `edge` block followed by the source fixture's bytes), `invalid-syntax` (the format's parser raises), `invalid-encoding` (strict decode with the declared charset raises), `nonstandard` (strict parser raises, lenient parser succeeds), `bom` (decodes after stripping the BOM; parser succeeds on the stripped text), `stress` (parses; the recorded `props` document the depth/size), `hostile-name` (parses; at least one entry name contains `../`), `polyglot` (**both** the announced format's reader and the one named by `edge.also_valid_as` accept the bytes; the prop `also_valid_as` records the second format). Only fixtures under `edge/` carry these; unusual-but-valid fixtures elsewhere (`txt/control-characters.txt`, `txt/nul-bytes.txt`) have `edge_case: true` and ordinary props |

#### 1.3.1 The four edge props (what is wrong, and what to expect)

A broken file is only useful if you know how it is broken. Four props say so, and none of
them is written by hand: `loremfile validate` measures or derives each one from the bytes
and refuses the fixture when the answer disagrees with the catalog.

| Prop | What it is |
|---|---|
| `damage` | One sentence about the bytes: where the file stops, which structure is missing, where a parser gives up. Composed from what the validator measured, so every number in it was counted on the file it describes. |
| `outcome` | `must-fail`, `may-recover` or `varies`; see below. |
| `compare_with` | The valid fixture of the same announced type. Feed your reader both: a reader that refuses everything is not the same as one that refuses this. |
| `derived_from` | The published fixture this one was cut or copied from, present on the six that have one and absent on the other thirteen. The validator reads that file and checks the relationship: a truncation's length must equal the recorded fraction of it and be a prefix of it, and a mislabelled file must equal it byte for byte. |

`outcome` describes the file, not your reader. It is derived by offering the bytes to the
reader for the type the file announces and, when that refuses them, to a tolerant reading
the format itself permits:

- **`must-fail`**: nothing conforming gets anything out of it. An empty JSON file has no
  value to return, and a trailing comma has no reading RFC 8259 allows. A parser that
  succeeds here is wrong.
- **`may-recover`**: part of the content survives and a conforming reader may return it: a
  PDF reader rebuilding a lost cross-reference table, a JPEG decoder painting the scan lines
  that arrived, U+FFFD substitution for ill-formed UTF-8.
- **`varies`**: readers legitimately disagree. Either one takes the file whole while
  another refuses it (a mislabelled file read by content rather than by name, a BOM that
  RFC 8259 lets a parser ignore), or two take it whole and disagree about what it *is*:
  a polyglot, where nothing in the bytes decides the type.

**`may-recover` and `varies` mean a parser that recovers is not wrong.** Only `must-fail`
says failure is the required behaviour, so only `must-fail` belongs in a test that asserts
your code refuses the file. For the other two, assert that your code does not crash, lose
data silently or hang, not that it fails.

#### 1.3.2 `contains_text` (what a correct reader must find)

Three to five strings each file is known to contain, so a parser test can check that a file loaded correctly and not only that it loaded. It is deliberately containment rather than equality: readers differ in whitespace, line breaks and the order of blocks, so the text one reader extracts is right for that reader alone, and no extracted text is published. Each string is in the text a correct reader returns once every run of whitespace is collapsed to one space; nothing here says what else that text holds or in what order.

- **Source.** The strings are taken from the generator's own input (the lorem it drew, the dataset values it read, the literals it wrote), never from a reader's output. They are declared in the catalog, and a validator publishes them only after a real reader has found every one in the bytes.
- **What CI checks.** CI regenerates every file that carries them, confirms the bytes are the published ones, and checks each string three ways: the generator's input holds it; a real reader finds it (pypdf, python-docx, python-pptx, openpyxl, html5lib for HTML and EPUB, markdown-it-py for Markdown); and no other file of the same format that carries the field holds the whole set, so a wrong file fails. The reader's output is used for that check only.
- **Encrypted PDF.** The strings are in `pdf/a4-encrypted-1page.pdf` once it is opened with the `user_password` in its `generator_params`.
- **Where it is absent.** Files with no text layer (`pdf/blank-1page.pdf`, `pdf/scanned-1page.pdf`) or one word (`pdf/minimal.pdf`); the sized files, whose text only fills them to a size; `xlsx/1sheet-10rows.xlsx`, `xlsx/3sheets.xlsx` and `xlsx/with-frozen-header-and-autofilter.xlsx`, every value of which `xlsx/1sheet-1000rows.xlsx` also holds; `xlsx/1sheet-100k-rows.xlsx`, which holds those values and 99,000 more records and is too large to read through for this; `xlsx/with-chart.xlsx`, whose cells hold no string of eight characters; `pdf/a4-with-images-2pages.pdf`, whose only text is two labels; RTF, which the toolchain has no reader for; and plain text, CSV and JSON, where the text is the file.

### 1.4 JSON Schema

`src/loremfile/schema/manifest-v1.json` (deployed at `/schema/manifest-v1.json`). Draft 2020-12. For `status: active` the required fields are exactly those in §1.2 except `notes`; `additionalProperties: false` so drift is caught. For `status: removed` the entry is a tombstone (§1.5) validated by an `if/then` branch. CI validates the manifest on every run (`tests/unit/test_manifest.py`). The schema document is itself immutable once published; a new schema is `manifest-v2.json` and bumps `schema_version`. **A new entry field is such a change, and no edit to v1 is allowed for it.** On 2026-11-13 #153 added `aliasOf` to v1 anyway: the document is served with an immutable cache header and was never purged, so the edge kept the old copy, `verify-live` read the difference as a hash mismatch, and because the entry definition is `additionalProperties: false` a client holding the old copy rejected all 75 alias entries. 1.15.1 restored the file to its bytes at `285fda6` and dropped the field: whatever a reader needs is derived from fields that already exist (the alias rule in §1.2). `tests/unit/test_manifest_schema_pinned.py` pins the file's SHA-256, and a deploy purges it anyway (`09` §6).

### 1.5 Tombstone entry (`status: removed`)

```json
{ "path": "html/example.html", "format": "html", "ext": "html", "mime": "text/html; charset=utf-8",
  "bytes": 1234, "sha256": "…", "status": "removed", "removed_at": "2027-03-01T10:00:00Z",
  "reason": "Legal request #12 (summary)", "added_in": "1.2.0", "description": "…", "phase": 1 }
```

Exactly these fields, nothing else; `url` is omitted so clients that iterate `url` skip it. `sha256`/`bytes` stay so archives can still be verified. `sha256sums.txt`, `formats.json`, `{format}/index.json` and `llms-full.txt` list active fixtures only; the site shows a tombstone line on the format page.

## 2. `sha256sums.txt`

GNU coreutils format, one line per active fixture, sorted by path:

```
9f86d0818…a08  pdf/a4-3pages.pdf
```

Two spaces between hash and path, LF line endings, UTF-8, no BOM, trailing newline. Generated from the manifest; never hand-edited.

## 3. `formats.json`

```json
{ "catalog_version": "1.0.0", "formats": [ { "format": "pdf", "count": 14, "total_bytes": 23456789, "url": "https://loremfile.dev/pdf", "index": "https://loremfile.dev/pdf/index.json", "mime_default": "application/pdf" } ] }
```

## 4. `{format}/index.json`

Same shape as `manifest.json` but `fixtures` filtered to one format (active only), `count` and `total_bytes` are the **per-format** values, and there is no top-level `formats` array. Stored as `_formats/{format}.json` and served at this URL by a rewrite, because `{format}/` is a locked prefix (ADR-032).

## 5. `llms.txt` and `llms-full.txt`

Follow the llmstxt.org layout (H1 title, blockquote summary, H2 sections with link lists).

`llms.txt` (short, ≈ 2 KB):

```
# loremfile.dev

> Free, CC0, hotlink-friendly sample files and test fixtures for every common file type. Stable URLs, open CORS, byte-range support, SHA-256 manifest. No ads, no signup, no rate-limit keys.

## How to use
- Every fixture: {format}/{name} under the site root, for example https://loremfile.dev/pdf/a4-1page.pdf (the manifest lists every path)
- Machine-readable list of everything: https://loremfile.dev/manifest.json (JSON, includes sha256, bytes, mime, measured properties)
- Per-format lists: {format}/index.json, for example https://loremfile.dev/pdf/index.json
- Any format or guide page as Markdown: append /index.md to its URL, for example https://loremfile.dev/pdf/index.md or https://loremfile.dev/testing/uploads/index.md
- Verify: https://loremfile.dev/sha256sums.txt
- Verify from a page alone: the JSON-LD Dataset on every format and guide page gives each file's contentSize and sha256, so a download can be checked without the manifest
- MCP server for agents: `npx -y loremfile mcp` or `uvx loremfile mcp`, three read-only tools (list_fixtures, describe_fixture, verify_file): https://loremfile.dev/docs/mcp

## Formats
- [PDF](https://loremfile.dev/pdf): A4/Letter, 1–100 pages, images, tables, links, outline, encrypted, exact-ish sizes 1 MB / 10 MB
- [Images](https://loremfile.dev/png): png, jpg, gif, webp, avif, svg, bmp, tiff, ico …
...

## Testing guides
- [Sample files for testing file uploads](https://loremfile.dev/testing/uploads): one line on what it covers
...

## Rules
- Query strings are ignored. Stay under 30 requests/second per IP.
- License: CC0 1.0 for all fixtures. Source: https://github.com/kumarprabhashanand/loremfile
```

`llms-full.txt` (≈ 60–100 KB): the same header, then for each format a table of every fixture: path, bytes, one-line description, key props. Regenerated from the manifest on every deploy.

**Neither file ever lists `/legal/imprint` or `/legal/privacy`** (ADR-016 amendment, ADR-028). Neither lists legal pages today; this is a rule the builder must keep, not a removal.

## 5b. Markdown twins (`/{x}/index.md`)

Each format page and each of the three testing guides has a Markdown twin at its URL plus `/index.md`: `/pdf/index.md`, `/testing/uploads/index.md`. A twin is the page for a reader that wants text rather than HTML: the H1, the description, a line linking the page, then the page's prose with each `<!-- file: PATH -->` marker expanded into a table of path, size, media type and measured props (consecutive markers share one table). A format page's twin adds the full file table, any superseded paths with their replacements, and the URL of the same list as JSON. Every number is the manifest's, as on the HTML page, and a marker the page may not list stops the build.

- **Stored under `_formats/`** (`_formats/pdf.md`, `_formats/testing/uploads.md`) and served by the same rewrite as `index.json` (`08` §5.2). An object under a locked format prefix can never change again, and a twin has to change whenever its page's copy does.
- Served as `text/markdown; charset=utf-8`, cached like the pages, with the headers every dotted path carries, `X-Robots-Tag: noindex` included. There is no `Link: rel="canonical"` header: noindex already keeps a twin out of search, and the two would contradict each other (owner, 2026-10-11).
- Not in `sitemap.xml`, `search-index.json` or `llms.txt`, and no `Accept` negotiation: `/pdf` always answers HTML.
- **Advertised since 2026-10-12**, after the twins answered in production: every format page and guide carries `<link rel="alternate" type="text/markdown">` to its twin, and `llms.txt` states the `/index.md` pattern under How to use, the only two ways an agent learns a twin exists, since nothing looks for `.md` by convention. A test requires every advertised twin to exist in the build, for every page a later change adds as well.
- The catalog refuses the fixture names `index.json` and `index.md` (`03` §1), so no fixture can sit at a twin's URL.

## 6. `robots.txt`

```
User-agent: *
Content-Signal: search=yes, ai-input=yes, ai-train=yes
Allow: /

User-agent: GPTBot
User-agent: OAI-SearchBot
User-agent: ChatGPT-User
User-agent: OAI-AdsBot
User-agent: ClaudeBot
User-agent: Claude-User
User-agent: Claude-SearchBot
User-agent: CCBot
User-agent: PerplexityBot
User-agent: Perplexity-User
User-agent: Bytespider
User-agent: meta-externalagent
User-agent: meta-externalfetcher
User-agent: Amazonbot
User-agent: Diffbot
User-agent: MistralAI-User
User-agent: DuckAssistBot
User-agent: AgentDataBot
User-agent: BixelBot
User-agent: CloudflareBrowserRenderingCrawler
User-agent: Kimi-Agent
User-agent: qodercli
User-agent: KeenableBot
User-agent: Keenable-User
User-agent: GrokBot
User-agent: GrokAppAndroid
User-agent: Hunyuan
User-agent: MoonshotBot
User-agent: xAI-Grok
User-agent: YiBot
User-agent: KimiBot
User-agent: Kimi-SearchBot
User-agent: Kimi-User
User-agent: CledaraBot
User-agent: Codex
User-agent: ElevenlabsBot
User-agent: ExaUser
User-agent: HarkBot
User-agent: Instinct
User-agent: Muse
User-agent: ElevenlabsCrawler
User-agent: ScryBot
User-agent: ExaSearchBot
User-agent: AIWebIndex
User-agent: Claude-Agent
User-agent: Google-Extended
User-agent: Applebot-Extended
Content-Signal: search=yes, ai-input=yes, ai-train=yes
Disallow: /legal/imprint
Disallow: /legal/privacy

User-agent: __usage_ai-training
Allow: /
Disallow: /legal/imprint
Disallow: /legal/privacy

Sitemap: https://loremfile.dev/sitemap.xml
```

AI crawlers are deliberately allowed (the audience includes agents). Raw fixtures carry `X-Robots-Tag: noindex`; pages are indexable, **except the two legal pages that name the operator** (ADR-016 amendment, ADR-028).

- **`User-agent: *` keeps `Allow: /`.** Google honours `noindex` only on a page it is "not … blocked by a robots.txt file"; disallowing the legal pages for everyone would stop search engines from ever seeing the `noindex` that keeps them out.
- **The named group replaces the `*` group for those crawlers, and disallows only the two paths**; everything else stays allowed for them. Each token is checked against its vendor's own documentation wherever the vendor publishes any, and the standing rule below says what happens when it publishes none: OpenAI documents `GPTBot`, `OAI-SearchBot`, `ChatGPT-User` and `OAI-AdsBot` ("OAI-AdsBot only visits pages submitted as ads, and the data collected by OAI-AdsBot is not used to train generative AI foundation models"), and says of `ChatGPT-User` that "robots.txt rules may not apply" to user-initiated actions; Anthropic documents `ClaudeBot`, `Claude-User` and `Claude-SearchBot` as robots.txt user agents; Google documents `Google-Extended` as a robots.txt token that "does not impact a site's inclusion in Google Search".
- **`Google-Extended` and `Applebot-Extended` send no requests of their own.** Google says `Google-Extended` "doesn't have a separate HTTP request user agent string"; Apple says `Applebot-Extended` "does not crawl webpages" and only controls how Applebot's data is used. Both belong here and **never** in a user-agent-matching rule, where they could not fire.
- **Checked against each operator's own documentation (2026-09-22), with the token in the casing that operator publishes**: `CCBot` (Common Crawl, `CCBot/2.0`), `PerplexityBot` and `Perplexity-User` (Perplexity; the second "generally ignores robots.txt", which is why the WAF rule matters), `meta-externalagent` and `meta-externalfetcher` (Meta publishes them lower-case in the user agent), `Amazonbot` (`compatible; Amazonbot/0.1`), `Diffbot`, `MistralAI-User` (Mistral also runs `MistralAI-Index` and `MistralAI-Training`), `DuckAssistBot` (`DuckAssistBot/1.2`) and `Applebot-Extended`. **`Bytespider` is the one token vouched for by someone other than its operator**: ByteDance publishes no crawler documentation, and Cloudflare's AI Crawl Control bot reference lists it as `Bytespider | ByteDance | AI Crawler` (read 2026-09-22).
- **Four proposed tokens are deliberately absent, because nobody documents them.** `anthropic-ai` and `claude-web`: Anthropic's crawler page names only `ClaudeBot`, `Claude-User` and `Claude-SearchBot`. `cohere-ai`: Cohere's own page says it runs no crawling bots "at this time" and names none. `archive.org_bot`: the Internet Archive's help pages do not name it, though a *verified* archiver is refused by category at the edge (`08` §5.7). `ia_archiver`: that token belongs to Alexa Internet, retired in 2022, so a clause for it could not fire. Adding any of them is a decision to drop this section's rule, not a detail.
- **Five more, weighed 2026-09-28 (`crawler-watch`, old issue #27), all five refused.** The evidence is not equal across them and the record says so. `CloudflareBrowserRenderingCrawler` is the only one its operator documents: Cloudflare publishes the user agent as `CloudflareBrowserRenderingCrawler/1.0`, "not customizable", for Browser Rendering's `/crawl` endpoint, and calls it a verified bot that honours robots.txt (read 2026-09-28). It is verified under *intermediary agent*, which is **not** one of the four categories this rule matches, so the token clause is what refuses it. `qodercli` is Qoder's terminal coding agent; their documentation names the command but publishes no user agent, so the bare token is what the rule matches. `Kimi-Agent` is Moonshot AI's browsing agent. Moonshot does publish a crawler page, but `Kimi-Agent` is not named on it (corrected 2026-10-22: this said there was no crawler page at all; the decision stands). `AgentDataBot` and `BixelBot` are listed with the operator "unclear at this time", so there is no operator to check them against: the list is the only source, as it is for `Bytespider`.
- **`qodercli` and `Kimi-Agent` are refused as user-directed agents, not as crawlers.** Both fetch because a person asked them to, which is the same category as `ChatGPT-User`, `Claude-User` and `Perplexity-User`, already refused here since 2026-09-22. The two pages name the operator; the rule is about who ends up holding that name, not about why they came. Being user-directed is a reason robots.txt may not be obeyed, which is exactly why the WAF rule exists.
- **Two more, weighed 2026-10-07 (#51), both refused, both documented by their operator.** Keenable publishes its agents on its own crawler page, with full user-agent strings: `KeenableBot` (`Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; KeenableBot/1.0; +https://keenable.ai/bot)`) "collects publicly available pages to build and maintain the Keenable search index", which answers queries from AI agents and applications; and `Keenable-User` (the same string with `Keenable-User/1.0`) "identifies requests we make on behalf of a person, or an agent acting for one … It does not crawl the web automatically." `KeenableBot` came from `crawler-watch`. **`Keenable-User` is refused under the rule above for user-directed agents** (`qodercli`, `Kimi-Agent`), and it is **not on the crawler list** the watch reads, so the weekly watch would never have raised it.
- **Weighed 2026-10-15 (#96), under the standing rule below.** `GrokBot` and `GrokAppAndroid` are added. The list names xAI as their operator with the function "AI Search Crawlers", and xAI publishes no crawler page (x.ai and docs.x.ai searched 2026-10-15), so both are the list's spelling, as `AgentDataBot` and `BixelBot` are. Before the change both answered `200` on `/legal/privacy` while `GPTBot` answered `403`: neither is a verified bot, so the category clause did not cover them. **`nbot` is weighed and deferred (reviewer, 2026-10-15), under the first guard,** and recorded with both reasons under `deferred` in `infra/crawlers-seen.json`, so the watch no longer raises it. NBot publishes no user agent (nbot.ai read 2026-10-15), and a case-sensitive `contains "nbot"` would also refuse every user agent containing those four letters, among them `Amazonbot` (already refused) and `msnbot`, which third-party crawler references describe as Microsoft's older search crawler; Microsoft's own crawler page did not render for checking. A capitalised `NBot` would not match it at all. If NBot publishes an exact string, ADR-033's exception allows blocking it with an exact match.
- **Weighed 2026-10-22 (#110), under the standing rule below.** `Hunyuan` (Tencent, a training crawler), `MoonshotBot` (listed under Kimi as a training crawler), `xAI-Grok` (xAI, classified as training because it is automated collection rather than a user-triggered fetch) and `YiBot` (01.ai) are added in the list's spelling, because no operator publishes a crawler page for them. The evidence for "publishes none": searches found only third-party directories (reviewer, 2026-10-22); Cloudflare's AI Crawl Control bot reference, "a selection of crawlers", lists none of the four (read 2026-10-22); 01.ai's robots.txt holds only `User-agent: *` and `Allow: /` (read 2026-10-22); and xAI was searched for #96 on 2026-10-15. `MoonshotBot` is absent from Moonshot's own crawler page, so it is the list's spelling, not Moonshot's.
- **Moonshot's own three, a separate decision the same day (#110).** `KimiBot` ("may be used to train Kimi's foundation models"), `Kimi-SearchBot` (builds Kimi's search index) and `Kimi-User` (fetches for actions a person starts in Kimi) are added in Moonshot's casing, as its crawler page publishes them (`https://www.kimi.ai/policies/kimi-crawlers`, read 2026-10-22). All three are documented by their operator, all three fall in categories already refused for every other operator (training, AI search, user-directed), and all three are on the 2026-09-22 snapshot in `infra/crawlers-seen.json`, so the watch could never raise them: the `Keenable-User` case. The page says of `Kimi-User` that "because actions are user-triggered, robots.txt rules may not directly apply", which is why the WAF clause carries it.
- **Weighed 2026-10-26 (#110), under the standing rule below: twelve reported, seven added, five not.** `CledaraBot`, `Codex`, `ElevenlabsBot`, `ExaUser`, `HarkBot`, `Instinct` and `Muse` are added in the list's spelling. The list classes four of them "AI Agents", one "AI Coding Agents" and two "AI Assistants", which is the `qodercli` and `Kimi-Agent` category: they fetch because a person asked, and this section has refused that category since 2026-09-22. Two of the seven have an operator that publishes a crawler page and does not name them, the `MoonshotBot` case: OpenAI's page names `OAI-SearchBot`, `OAI-AdsBot`, `GPTBot` and `ChatGPT-User` and not `Codex` (read 2026-10-26), and Meta's names `FacebookExternalHit`, `Meta-WebIndexer`, `Meta-ExternalAds`, `Meta-ExternalAgent` and `Meta-ExternalFetcher` and not `Muse` (read 2026-10-26). The other five are listed with the operator "Unclear at this time", so there is no operator page to check them against and the list is the only source, as it was for `AgentDataBot` and `BixelBot` (corrected 2026-11-02, #131: `ElevenlabsBot` is one of the five, and ElevenLabs does publish a bots page that names it in this casing, read 2026-11-03; corrected 2026-11-06: `ExaUser` is another, named on Exa's crawler page, read 2026-11-06; the decision and the spelling stand for both). Each of the seven was checked as a case-sensitive substring against all 200 names on the list and against the search-engine and general-crawler tokens, and none collides. **Reading Meta's page for every token it publishes, as the bullet below requires, turned up two this group does not hold**: `Meta-WebIndexer`, which Meta says "navigates the web to improve Meta AI search result quality", and `Meta-ExternalAds`. `meta-webindexer` is on the 2026-09-22 snapshot in `infra/crawlers-seen.json`, so the watch can never raise it, which is the `Keenable-User` shape; whether it belongs in this group is left open for the reviewer rather than taken in passing.
- **`Dot` is weighed and deferred (reviewer, 2026-10-26), under the first guard,** and recorded with its reasons under `deferred` in `infra/crawlers-seen.json`, so the watch no longer raises it. At three characters a case-sensitive `contains "Dot"` also refuses Moz's link-index crawler, which Moz's own page calls "Moz's web crawler" for "the Moz Link Index" and spells `DotBot` in the page title, `Dotbot` in its prose and `dotbot` in its robots.txt examples (`https://moz.com/help/moz-procedures/crawlers/dotbot`, read 2026-10-26): two of those three casings contain `Dot`, and that crawler is nothing this group is aimed at. The list gives `Dot` no operator and OpenAI's crawler page does not name it, so there is no published string to match exactly either. If one is published, ADR-033's exception allows blocking it with `http.user_agent eq`.
- **Four are rejected as display names rather than product tokens (2026-10-26, #110), under the third guard below.** `AGI Agent`, `CartAI Agentic Commerce`, `Grok Bot` and `Payhawk Invoice Fetching Agent` each contain a space. RFC 9309 §2.2.1: "The product token MUST contain only uppercase and lowercase letters ("a-z" and "A-Z"), underscores ("_"), and hyphens ("-")", so no `User-agent:` line can carry any of the four, and a WAF `contains` clause for one would fire only on a user agent holding that literal string, space included. `Grok Bot` is xAI's, and xAI is the operator already refused here as `GrokBot` since #96. All four are recorded under `deferred` with that reason, so the weekly watch stops raising them, and `tests/unit/test_legal_pages.py` holds both the robots group and the rule to tokens without whitespace, with a control that the check fires.
- **Weighed 2026-11-02 (#131), under the standing rule below: two reported, both added.** `ElevenlabsCrawler` and `ScryBot` are added in the list's spelling, which for the first is also the operator's. ElevenLabs documents `ElevenlabsCrawler` on its bots page (`https://elevenlabs.io/docs/bots`, read 2026-11-03): it "crawls the web to collect content that may be used to train ElevenLabs' generative AI models", its full user agent is `Mozilla/5.0 (compatible; ElevenlabsCrawler/1.0; +https://elevenlabs.io/docs/bots)`, and disallowing it "indicates that a site's content should not be used for training". The page says of `ElevenlabsBot` that it "honors `robots.txt`" and says nothing of the kind about the crawler, which is the case the WAF clause is for. The page publishes exactly two tokens, so reading it for every token, as the bullet below requires, found nothing that is not refused: `ElevenlabsBot` has been since 2026-10-26, and an operator refused under one token is now refused under both, as Keenable has been since #51. `ScryBot` is Scry's (scry.io), listed as "Used with AI agents to scrape data for answers to queries", and Scry publishes no crawler documentation: `scry.io/robots.txt` names no such token, the home page mentions no crawler, user agent or robots.txt, and `/bot`, `/crawler` and `/scrybot` answer with the home page's bytes, as a path that does not exist does (all read 2026-11-03). The one other source is a third-party catalogue, Centinel Analytica's, which lists it as a "Crawler operated from scry.io" that "describes itself as an ethical crawler of public pages" and says "The operator publishes no further documentation that we could confirm" (`https://docs.centinelanalytica.com/crawlers/scrybot`, read 2026-11-03), so there is no published user-agent string either. Each was checked as a case-sensitive substring against all 202 names on the list and against 55 search-engine, SEO-crawler, link-preview and general-client tokens, in both directions, and none collides; neither contains whitespace, so the first and third guards below are clear.
- **Weighed 2026-11-06 (owner's brief), under the standing rule: `ExaSearchBot` and `AIWebIndex` added.** Both were observed in the zone's traffic; ADR-017 keeps any figure out of the repository, so none is recorded. Both are on the 2026-09-22 snapshot in `infra/crawlers-seen.json`, so the watch could never have raised them (the `Kimi-User` case) and that file is unchanged. Both operators publish the token. Exa's crawler page (`https://crawler.exa.ai/`, last updated 2 November 2026, read 2026-11-06) gives the user agent `Mozilla/5.0 (compatible; ExaSearchBot/1.0; +https://crawler.exa.ai/)` and says "Its robots.txt product token is ExaSearchBot". It also names `ExaUser` for fetches made on a user's request, and `ExaSearchBot-Images` for the images of crawled pages, which the clause for `ExaSearchBot` already matches. Exa calls itself "a search engine" but serves an index to applications and agents, the `KeenableBot` shape, so the first guard's exclusion of general web search engines is read as not reaching it; that reading is the reviewer's to overrule. Lyrenth's page (`https://lyrenth.com/bot`, read 2026-11-06) gives `AIWebIndex/2.0 (+https://lyrenth.com/bot; AI-readable web index)` as the user agent and `User-agent: AIWebIndex` in its own opt-out example, so the token is `AIWebIndex` and the rest is a display string (third guard). It publishes a second agent, `AIWebIndex-Agent/2.0`, for on-demand fetches: the clause for `AIWebIndex` matches it at the edge, and it has no robots.txt line of its own. Each token was checked as a case-sensitive substring against the 204 names on the upstream list and the 2,124 user-agent strings of the public `crawler-user-agents` list (both read 2026-11-06): `ExaSearchBot` is in none, `AIWebIndex` only in its own crawler's. `tests/unit/test_legal_pages.py` now holds the first guard against fourteen search-engine user agents, with a control. Whether Cloudflare already classifies either token is not established: Radar answers `403` to a plain client (read 2026-11-06); Exa says only that Cloudflare validates `ExaSearchBot` at the edge through Web Bot Auth; Lyrenth says Cloudflare lists both its agents as verified bots in a "Search" category, which is the operator's claim and not one of the four categories the rule matches. The token clause is what refuses them either way.
- **Weighed 2026-11-09 (#141, owner's brief), under the standing rule: `Claude-Agent` added.** The list describes it as Anthropic's cloud browser agent for Claude Duet but gives its operator as "Unclear at this time.", which is why the watch printed it as undecided; Anthropic's own pages settle that. Its crawler page (`https://support.claude.com/en/articles/8896518`, read 2026-11-09) lists `Claude-Agent` and points to a second article (`https://support.claude.com/en/articles/18234133`, read 2026-11-09). That article says the traffic comes from a real browser on Anthropic's infrastructure and carries the browser's own user agent "with the addition of the token Claude-Agent", gives `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-Agent/1.0) Chrome/154.0.0.0 Safari/537.36` as its example, says to "match on the Claude-Agent token rather than the full string", and publishes the addresses at `https://claude.com/.well-known/sail`. Anthropic is already refused under `ClaudeBot`, `Claude-User` and `Claude-SearchBot`, and the precedent is that an operator refused under one token is refused under all (`KeenableBot` and `Keenable-User` since #51, `ElevenlabsBot` and `ElevenlabsCrawler` since #131); `tests/unit/test_legal_pages.py` now holds those families. The guards: (1) `Claude-Agent` is in none of the 2,124 user-agent strings of the public `crawler-user-agents` list and none of the 204 names on the upstream list (both read 2026-11-09), no existing token is a substring of it or contains it, and an ordinary Chrome user agent does not match; (2) the expression goes from 2,109 to 2,152 characters and 45 tokens, below the budget line; (3) the token is letters and a hyphen, no whitespace; and our own checks' agents do not contain it (the fourth guard). The article describes allowing or disallowing "this traffic" without naming robots.txt, so the WAF clause is what refuses it and the robots.txt line asks, as for the others. It also says anyone can send the same user agent and recommends checking the published addresses; a `contains` clause does not, and does not need to, because the two pages are refused to anything that claims the name.
- **`__usage_ai-training` is written in robots.txt and never in the WAF rule (weighed 2026-11-09, written 2026-11-10, #141), because it is a policy token and not an agent.** The upstream list gives it the operator "Not applicable." and calls it "a policy token defined in an Internet Draft" (read 2026-11-09). That draft, `draft-kelley-aipref-training-preference-signal-00` (Anthropic, 30 October 2026, Standards Track, expires 3 May 2027, read 2026-11-09), keys ordinary robots.txt groups on a per-purpose token in the `User-agent:` line: a path such a group allows carries a preference in favour of AI training, a path it disallows carries one against, and a file with no such line "has expressed no preference" (§4.2). A policy token "need not appear in the User-Agent header field of any outbound request", so no request carries the name, a `contains` clause for it would match nothing, and it belongs in robots.txt only, as `Google-Extended` and `Applebot-Extended` do. **The group written here is `Allow: /` with the two legal pages disallowed**, which states in one cross-vendor place what the 45 request-sending tokens of the group above state one operator at a time, and what `Content-Signal: ai-train=yes` states with no paths. It carries no `Content-Signal` line of its own: nothing crawls under a policy token, so a signal there would reach nobody, and `tests/unit/test_agent_discovery.py` holds that omission with the two crawl groups as its control. Consumers "MUST match policy tokens exactly, apart from case", and `User-agent: *` groups "MUST NOT be matched" to them, so no crawler loses a path through this group and the `*` group still says `Allow: /`. **The risk taken is the draft's age**: an individual submission at `-00`, eleven days old when this was written, and a token renamed before the working group adopts it leaves a group no consumer reads, which is one line to change here and one in `build.py`. The reverse risk is worse for this site: silence reads as no preference, and everything here is CC0 and meant to be trained on. `infra/crawlers-seen.json` keeps the record of what was weighed, and the token now resolves through robots.txt, so the watch stays quiet on it either way.
- **What the watch covers, and what it cannot.** `crawler-watch` reads a list of crawlers. User-directed agents are mostly not on it, so they have to be found in the operator's own documentation, as `Keenable-User` was, next to the crawler that brought the operator to our attention. When a new operator is weighed, read its crawler page for every token it publishes, not only the one the watch named.
- **Standing rule (reviewer, 2026-10-15): an AI token the weekly watch reports is added without asking.** A token `crawler-watch` reports as an AI crawler, AI assistant or AI search crawler goes into this group and the WAF rule, by whoever works the advisory, in the casing its operator publishes, or the list's spelling when the operator publishes none, with the evidence recorded in this section. Names already in `infra/crawlers-seen.json` were weighed and stay as they are. Four guards send a token to the reviewer instead:
  - **Never a general web search engine's token, nor one a search engine's user agent contains.** The two pages must stay crawlable by search engines for their `noindex` to be honoured (the first bullet above), and the WAF clause is a case-sensitive `contains`, so a token also refuses every user agent that contains it. **Exception (ADR-033):** such a token may still be blocked by an exact match on the operator's published user-agent string (`http.user_agent eq`), because the collision rules out `contains`, not the crawler.
  - **The budget line: 75% of the 4,096-character limit, 3,072 characters.** Past it the next tokens mean splitting the rule, which is a decision. `crawler-watch` reports a rule past the line in the advisory (exit 1), and `tests/unit/test_crawler_watch.py` fails a pull request that crosses it.
  - **Never a name with whitespace in it (2026-10-26).** RFC 9309 §2.2.1 confines the product token to letters, underscores and hyphens, so a name with a space is a display name and cannot be a `User-agent:` line at all, while a `contains` clause for it would match only a user agent carrying the space as written. The list publishes display names beside product tokens and marks neither, so the reviewer decides whether the operator publishes a usable token instead: `Grok Bot` turned out to be `GrokBot`, already refused, and the other three of 2026-10-26 had nothing behind them.
  - **Never a substring of the agent our own checks send (2026-11-08).** `verify-live`, the release archive and `probe` fetch both legal pages, so a token that `loremfile-verify/…` or `loremfile-probe/…` contains is a `403` on every deploy's check. The agents are `VERIFY_USER_AGENT` and `PROBE_USER_AGENT` in `config.py` (`08` §5.7), and `tests/unit/test_legal_pages.py` holds both against every token of the committed rule, so a colliding token fails its own pull request; the fix is a different agent name, not a dropped token. The match is case-sensitive: an agent called `…-Muse` would be held, `…-muse` would not.
- **Baseline.** 2026-10-15: before #96, 1,307 characters and 24 tokens; after `GrokBot` and `GrokAppAndroid`, 1,390 characters and 26 tokens, 33.9% of the limit. 2026-10-22, after #110's first seven: 1,668 characters and 33 tokens, 40.7% of the limit. 2026-10-26, after #110's second seven: 1,939 characters and 40 tokens, 47.3% of the limit, 1,133 below the budget line. 2026-11-02, after #131's two: 2,025 characters and 42 tokens, 49.4% of the limit, 1,047 below the budget line. 2026-11-06, after the Exa and Lyrenth pair: 2,109 characters and 44 tokens, 51.5% of the limit, 963 below the budget line. **2026-11-09, after `Claude-Agent`: 2,152 characters and 45 tokens, 52.5% of the limit**, 920 below the budget line. A token costs 31 characters of clause plus its own length, 42 on average over the 45, so about 22 more fit before the budget line and 46 before the 4,096-character cap. Measure with `len()` of the committed expression; record each change here so the trend is read, not re-measured.
- **robots.txt asks; a WAF custom rule refuses.** Every token in this group except `Google-Extended` and `Applebot-Extended` is also matched by the custom rule `loremfile_legal_pages_ai_agents` (`08` §5.7, ADR-030), which answers `403` on the two paths. `tests/unit/test_legal_pages.py` keeps the two lists equal.
- **The limit.** RFC 9309: robots.txt is "not a form of access authorization". These groups ask; they cannot enforce (`13` §3b).
- **`Content-Signal` states what the content may be used for**: search, AI input and AI training are all allowed, which is what CC0 already grants. Syntax as contentsignals.org publishes it (read 2026-09-21): a group member line before the group's rules, `key=yes|no` pairs separated by commas. It is in **both** groups because a crawler obeys only its most specific group (RFC 9309 §2.2.1); in the `*` group alone it would never reach the AI crawlers the named group matches. It grants nothing on the two disallowed paths: a signal is about use, and those paths are not to be fetched at all.

## 7. `sitemap.xml`

**The sitemap lists only pages meant to be indexed (2026-10-16).** `/legal`, `/legal/license` and `/legal/terms` stay indexable and linked from every footer, but the sitemap leaves them out (`NOT_IN_SITEMAP` in `site/build.py`). The reason is measurement, not tidiness: indexed-page count is the RISK-18 tripwire (`17`), and a sitemap that asks for pages nobody wants in search makes that count wrong by construction. The two operator pages were never listed; they are `noindex`.

**Every discovery file carries `X-Robots-Tag: noindex`, and that is not a bug to fix.**
The `files_headers` rule matches any path containing a dot, so `sitemap.xml`,
`robots.txt`, `llms.txt`, `manifest.json`, `search-index.json`, `sha256sums.txt`,
`formats.json` and `security.txt` all receive it alongside the fixtures. It looks alarming
next to a Search Console error and it is the wrong suspect: Google's own sitemap
troubleshooting lists robots.txt blocking, manual actions, 404s, server errors and low
crawl demand as the causes of "Couldn't fetch": `noindex` is not among them, and a
`noindex` sitemap is still fetched and read.

**The observation that prompted this (2026-09-17).** A Search Console submission reported
"Couldn't fetch" on a property verified minutes earlier, while the file served 200 to
Googlebot with 92 URLs. **Decision: no header change**; re-check after a few days, because
a just-verified property commonly reports that and resolves itself. This is written down
so the rule is not "fixed" later on a theory the documentation does not support: changing
`files_headers` to carve out the discovery files would alter the headers on every fixture
path, which is a real risk taken against an imagined cause.

**The decision stands after 2026-09-21.** Four display assets (`favicon.ico`, `apple-touch-icon.png`, `/assets/og.png`, `/assets/mark.svg`) were taken out of the noindex rule that day (`08` §5.3), because they exist to be *shown* by search engines and social platforms. That is not precedent for the discovery files: a sitemap does not need to be indexable to be fetched, and nothing in Google's documentation says otherwise.


Lists every page except the five under `/legal` (above). Does not list raw fixtures. **`lastmod` is the day the page's content last changed**, from `page-dates.json` (below), never the build's date or the clock. Under 50 MB / 50,000 URLs, so a single file suffices.

**`page-dates.json` (2026-10-21).** Until then every `lastmod`, and the `dateModified` of every format page and testing guide (§10), was the build's commit date, so the first deploy of each day rewrote every one of those pages with no content change (83 of 98 on 2026-10-17) and IndexNow announced them all (§12). The committed `page-dates.json` maps each sitemap page to the date its content last changed and the sha256 of the page **as rendered with no date at all**: hashed with its date, a page would change whenever its date did, and its date would move on every build. A page whose hash is unchanged keeps its date; one whose hash changed takes the committer date of `HEAD` (`07` §4), never earlier than its recorded date. `site build` refuses a stale record and `loremfile site build --update-dates` rewrites it; commit what it writes, like `manifest.json`, and never edit it by hand. Content is everything rendered into the page, so a template or stylesheet change that alters every page dates every page. The record was seeded at 2026-10-17, the date every page already carried and the last day any rendered content had changed, so a seeded date is each page's latest possible date rather than its true one. The legal pages are not in it; they are dated from the history of `13`.

## 8. `.well-known/security.txt` (RFC 9116)

```
Contact: https://github.com/kumarprabhashanand/loremfile/security/advisories/new
Contact: mailto:security@loremfile.dev
Expires: <one year from deploy, RFC 3339>
Preferred-Languages: en
Canonical: https://loremfile.dev/.well-known/security.txt
Policy: https://loremfile.dev/docs/security-policy
```

`Expires` is regenerated on every site build (committer date of the built commit + 365 days); the daily health check warns 30 days before expiry, which can only happen if no commit was deployed for 11 months.

## 9. `schema/manifest-v1.json`

Deployed copy of the JSON Schema (§1.4). `application/schema+json`, immutable cache headers, and a deploy purges it as insurance although it should never change.

## 10. Structured data on pages

JSON-LD per page type (single source of truth; `07` §3 refers here): home → `WebSite` + `SoftwareSourceCode` (pointing at the repository); format page → `Dataset` (`name`, `description`, `license: CC0`, `isAccessibleForFree: true`, `dateModified` (the page's date in `page-dates.json`, which the sitemap gives as `lastmod`, §7), and `distribution` with `contentUrl`, `encodingFormat`, `contentSize` (the manifest's byte count) and `sha256` per active fixture) + `BreadcrumbList`, and `<link rel="alternate">` to its `index.json` (`application/json`) and its Markdown twin (`text/markdown`, §5b); a testing guide carries the Markdown one; testing guide → the same `Dataset`, its `distribution` being exactly the files the guide names, + `BreadcrumbList`; `/formats` → `CollectionPage` whose `mainEntity` is an `ItemList` of every format page, in the table's order, + `BreadcrumbList`; docs, legal, the testing index and `/changelog` → `TechArticle` + `BreadcrumbList`, **except `/legal/imprint` and `/legal/privacy`, which carry no JSON-LD at all** (ADR-028). No `Organization`, `creator`, `publisher` or `author` node anywhere, and a test fails on one.

## 11. Agent discovery

Four static standards, checked by Cloudflare's agent-readiness scanner. None of them lists or links either legal page, and `site build` refuses one that does (`site/checks.py`).

- **`Content-Signal`** in robots.txt (§6).
- **`Link` on every page** (RFC 8288), set by the `site_pages_headers` rule: `</llms.txt>; rel="describedby", </.well-known/api-catalog>; rel="api-catalog"`. Registered relation types only: `sitemap` is not in the IANA registry, RFC 8288 requires an unregistered type to be a URI, and robots.txt already names the sitemap. The same rule matches `/.well-known/api-catalog`, because RFC 9727 §2 requires its `HEAD` to carry the relation.
- **`/.well-known/api-catalog`** (RFC 9727), served as `application/linkset+json; profile="https://www.rfc-editor.org/info/rfc9727"`; the key has no extension, so `routes.content_type` names it rather than defaulting to HTML. One linkset entry per data file an agent can use: `manifest.json` with its schema as `service-desc`, `sha256sums.txt`, and every `{format}/index.json`, each with `llms.txt` as `service-doc`. A per-format index has no `service-desc`: it lacks the manifest's `formats` array, so the manifest schema does not describe it.
- **`/.well-known/agent-skills/index.json`** (Agent Skills Discovery v0.2.0) listing one skill, `find-and-verify-fixtures` (`site/agent-skills/`): find a fixture by format or by the failure it should cause (the `edge` files' `outcome`, and `/testing/parsers`), fetch it, verify it against the manifest hash or the page's JSON-LD, or do the same through the MCP server. The index carries `$schema`, and the skill entry's `digest` is the SHA-256 of the `SKILL.md` bytes, computed at build. **One skill, not two (2026-10-12):** choosing a file for a failure case shares every step of finding and verifying one, so a second skill would repeat them and go stale twice. **Every agent-facing surface is in the skill or left out with a reason:** `tests/unit/test_agent_discovery.py` discovers the surfaces from the build (every built file that is neither a page nor a display asset, the per-format lists and twins as one each, and the MCP server and JSON-LD hashes from `llms.txt`'s How to use), so a new surface fails the build until someone decides whether agents should be told. Added after the MCP server, the twins and the JSON-LD hashes each reached agents without reaching `SKILL.md`.

## 12. IndexNow

Each deploy tells IndexNow which site pages it changed: one `POST https://api.indexnow.org/indexnow` with `host`, `key`, `keyLocation` and `urlList`, after `verify-live` has seen the pages served (`09` §3.2). `src/loremfile/infra/indexnow.py`; the command is `loremfile indexnow`.

- **Who reads it.** The participants indexnow.org lists in `searchengines.json` (read 2026-10-02): Bing, Yandex, Seznam, Naver, Yep, the Internet Archive and Amazon. One submission to the shared endpoint reaches all of them. **Google does not take part.** It learns about pages from `sitemap.xml` (§7) and its own crawl, and nothing here changes that.
- **Why, when Crawler Hints is on.** Cloudflare's Crawler Hints, enabled 2026-10-01, already sends IndexNow signals, inferred from cache misses. This names the pages a deploy actually wrote, read from the site upload's own report, so a page is announced once, when it changed, rather than whenever a cache entry happens to expire.
- **What is sent.** Changed pages only, and only pages the sitemap lists (§7): the keys `upload --site` wrote that are pages (`routes.is_page`), as absolute URLs on `loremfile.dev`. Never a fixture or any other file: they are files, not pages, and the site upload never writes a fixture anyway. **Never `/legal/imprint` or `/legal/privacy`.** Both are kept out of every index (ADR-028), and announcing them would contradict their `noindex` header and the WAF rule that refuses AI agents on them; two independent filters drop them, each tested on its own. `/legal`, `/legal/license` and `/legal/terms` are left out too, as the sitemap leaves them out. **At most 10,000 URLs**, IndexNow's per-request limit ("Submit no more than 10,000 URLs per request", indexnow.org FAQ, read 2026-10-21); a longer list sends the home page and the sitemap instead. Until 2026-10-21 the cap was 100, which a deploy that rewrote every page (a template change, a `force_site` run: 101 pages) already exceeded. Pages are only ever announced when a deploy changed them: the FAQ answers "Should I submit URLs that changed before I started using IndexNow?" with "No".
- **The key is public, by design.** It is `config.INDEXNOW_KEY` (`6f5cebccab35f5982434418d5d001e12`), served at `https://loremfile.dev/6f5cebccab35f5982434418d5d001e12.txt` holding exactly the key and nothing else, which is how an engine checks that a submission came from the host. IndexNow's documentation says only you and the engines should know the key, but its own root-file method serves the key to anyone, and all a key allows is telling the engines that URLs on this host changed. **It must never become a secret:** the build could not emit the file, and every submission would be refused with `403`. The file is a site key like any other. The upload publishes it, `verify-live` compares it byte for byte on every deploy, and nothing deletes it, because site keys are never removed (only tombstoned fixtures are, `09` §5). It is not in `sitemap.xml`, which lists pages, and a build check refuses it there.
- **It never fails a deploy.** `200` ("URL submitted successfully") and `202` ("URL received. IndexNow key validation pending.") mean accepted. Any other answer, or none, is logged with its status, and the command still exits 0; the step is `continue-on-error` besides. An engine refusing a notification changes nothing about what was published. A dry run, or an upload that wrote fewer keys than it planned, announces nothing, because which pages changed is then not known.
