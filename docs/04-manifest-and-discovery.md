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
| `props` | object | Measured by validators, format-specific (see §1.3). Frozen. |
| `generator`, `generator_params` | string, object | Enough to regenerate. Informational; may change if a generator is refactored (bytes must not). |
| `added_in` | semver | Catalog version that introduced it. |
| `status` | enum | `active`, `removed` (legal takedown tombstone, see §1.5). |
| `deprecated`, `supersededBy` | boolean, string/null | See immutability policy. |

### 1.3 `props` by format (what validators measure)

| Formats | Keys |
|---|---|
| pdf | `pages`, `page_width_pt`, `page_height_pt`, `encrypted`, `pdf_version`, `has_outline`, `has_images` |
| png, jpg, gif, webp, avif, bmp, tiff, ico | `width`, `height`, `mode` (`RGB`, `RGBA`, `L`, `P`, `CMYK`, `I;16`), `frames`, `animated`, `progressive`, `exif_orientation` (jpg), `sizes` (ico) |
| svg | `width`, `height`, `viewbox` |
| mp4, webm, mkv, mov, avi, ogv, ts, hls | `duration_ms`, `width`, `height`, `fps`, `vcodec`, `acodec`, `audio_streams`, `subtitle_streams`, `rotation`, `bitrate_kbps` (hls: `segments`, `target_duration_s`) |
| mp3, wav, flac, ogg, opus, m4a, aac, aiff | `duration_ms`, `sample_rate`, `channels`, `bit_depth` (pcm), `bitrate_kbps`, `codec`, `tags` (bool) |
| docx | `paragraphs`, `tables`, `images`, `sections`, `has_headers_footers` |
| xlsx | `sheets`, `rows` (first sheet, incl. header), `columns`, `has_formulas`, `has_charts` |
| pptx | `slides`, `has_notes`, `aspect` (`16:9`/`4:3`) |
| txt, md, html, css, js, rtf, srt, vtt, log, sql, ini | `encoding`, `bom`, `line_ending` (`lf`/`crlf`/`cr`/`mixed`/`none`), `lines`, `max_line_bytes` |
| csv, tsv | plus `rows` (data rows), `columns`, `delimiter`, `has_header`, `quoted_fields` |
| json, ndjson, geojson, har, ipynb, jsonld | `top_type` (`object`/`array`/`string`…), `items` (array length or ndjson lines), `max_depth` |
| xml, rss, atom, kml, gpx | `root_element`, `encoding`, `has_dtd`, `namespaces` |
| yaml, toml | `documents` (yaml), `top_keys` |
| parquet, avro, arrow | `rows`, `columns`, `compression` (parquet), `row_groups` |
| sqlite | `tables`, `rows_total`, `page_size`, `journal_mode`, `has_fts` |
| zip, 7z | `entries`, `directories`, `method` (`stored`/`deflate`/`lzma2`), `encrypted`, `zip64`, `comment` |
| tar (+gz/bz2/xz/zst) | `entries`, `compression`, `has_symlinks`, `pax` |
| gz, bz2, xz, zst | `members` (gz), `original_bytes` |
| ttf, otf, woff, woff2 | `glyphs`, `flavor`, `family_name`, `units_per_em` |
| bin | `pattern` (`shake256`, `zeros`, `ones`, `incrementing`) |
| ics | `events`, `has_vtimezone`, `has_rrule` |
| vcf | `cards`, `version` |
| eml, mbox | `messages`, `parts`, `attachments`, `has_html` |
| epub | `version`, `chapters`, `images` |
| pem, der | `kind` (`certificate`/`csr`), `algorithm`, `not_before`, `not_after` |
| wasm | `sections`, `exports` |
| edge/* | `intended_format`, `defect`, `source_fixture` (path or null). `defect` is a closed enum, and it tells the validator what to assert: `zero-byte` (bytes == 0), `truncated` (bytes == floor(`fraction` × source bytes) with `fraction` from the catalog's `edge` block, default 0.5 — `pdf-truncated-60pct.pdf` uses 0.6 — and prefix-equal to the source), `mismatched-extension` (bytes equal the source fixture; magic bytes match the *source* format, not the extension), `magic-prefix` (bytes == the `magic` value from the `edge` block followed by the source fixture's bytes; used by `exe-header-with-txt-extension.txt`), `invalid-syntax` (the format's parser raises), `invalid-encoding` (strict decode with the declared charset raises), `nonstandard` (strict parser raises, lenient parser succeeds), `bom` (decodes after stripping the BOM; parser succeeds on the stripped text), `stress` (parses; the recorded `props` document the depth/size), `hostile-name` (parses; at least one entry name contains `../`). Only fixtures under `edge/` carry `intended_format`/`defect`; unusual-but-valid fixtures elsewhere (`txt/control-characters.txt`, `txt/nul-bytes.txt`) have `edge_case: true` and ordinary props |

### 1.4 JSON Schema

`src/loremfile/schema/manifest-v1.json` (deployed at `/schema/manifest-v1.json`). Draft 2020-12. For `status: active` the required fields are exactly those in §1.2 except `notes`; `additionalProperties: false` so drift is caught. For `status: removed` the entry is a tombstone (§1.5) validated by an `if/then` branch. CI validates the manifest on every run (`tests/unit/test_manifest.py`). The schema document is itself immutable once published; a new schema is `manifest-v2.json` and bumps `schema_version`.

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
- Every fixture: https://loremfile.dev/{format}/{name} — see the manifest for all paths.
- Machine-readable list of everything: https://loremfile.dev/manifest.json (JSON, includes sha256, bytes, mime, measured properties)
- Per-format lists: https://loremfile.dev/{format}/index.json
- Verify: https://loremfile.dev/sha256sums.txt

## Formats
- [PDF](https://loremfile.dev/pdf): A4/Letter, 1–100 pages, images, tables, links, outline, encrypted, exact-ish sizes 1 MB / 10 MB
- [Images](https://loremfile.dev/png): png, jpg, gif, webp, avif, svg, bmp, tiff, ico …
...

## Rules
- Query strings are ignored. Stay under 30 requests/second per IP.
- License: CC0 1.0 for all fixtures. Source: https://github.com/kumarprabhashanand/loremfile
```

`llms-full.txt` (≈ 60–100 KB): the same header, then for each format a table of every fixture: path, bytes, one-line description, key props. Regenerated from the manifest on every deploy.

**Neither file ever lists `/legal/imprint` or `/legal/privacy`** (ADR-016 amendment, ADR-028). Neither lists legal pages today; this is a rule the builder must keep, not a removal.

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
User-agent: meta-externalagent
User-agent: meta-externalfetcher
User-agent: Amazonbot
User-agent: Diffbot
User-agent: MistralAI-User
User-agent: DuckAssistBot
User-agent: Google-Extended
User-agent: Applebot-Extended
Content-Signal: search=yes, ai-input=yes, ai-train=yes
Disallow: /legal/imprint
Disallow: /legal/privacy

Sitemap: https://loremfile.dev/sitemap.xml
```

AI crawlers are deliberately allowed (the audience includes agents). Raw fixtures carry `X-Robots-Tag: noindex`; pages are indexable — **except the two legal pages that name the operator** (ADR-016 amendment, ADR-028).

- **`User-agent: *` keeps `Allow: /`.** Google honours `noindex` only on a page it is "not … blocked by a robots.txt file"; disallowing the legal pages for everyone would stop search engines from ever seeing the `noindex` that keeps them out.
- **The named group replaces the `*` group for those crawlers, and disallows only the two paths** — everything else stays allowed for them. Each token is checked against its vendor's own documentation, and **no token is added without that check**: OpenAI documents `GPTBot`, `OAI-SearchBot`, `ChatGPT-User` and `OAI-AdsBot` ("OAI-AdsBot only visits pages submitted as ads, and the data collected by OAI-AdsBot is not used to train generative AI foundation models"), and says of `ChatGPT-User` that "robots.txt rules may not apply" to user-initiated actions; Anthropic documents `ClaudeBot`, `Claude-User` and `Claude-SearchBot` as robots.txt user agents; Google documents `Google-Extended` as a robots.txt token that "does not impact a site's inclusion in Google Search".
- **`Google-Extended` and `Applebot-Extended` send no requests of their own.** Google says `Google-Extended` "doesn't have a separate HTTP request user agent string"; Apple says `Applebot-Extended` "does not crawl webpages" and only controls how Applebot's data is used. Both belong here and **never** in a user-agent-matching rule, where they could not fire.
- **Checked against each operator's own documentation (2026-09-22), with the token in the casing that operator publishes**: `CCBot` (Common Crawl, `CCBot/2.0`), `PerplexityBot` and `Perplexity-User` (Perplexity; the second "generally ignores robots.txt", which is why the WAF rule matters), `meta-externalagent` and `meta-externalfetcher` (Meta publishes them lower-case in the user agent), `Amazonbot` (`compatible; Amazonbot/0.1`), `Diffbot`, `MistralAI-User` (Mistral also runs `MistralAI-Index` and `MistralAI-Training`), `DuckAssistBot` (`DuckAssistBot/1.2`) and `Applebot-Extended`.
- **Five proposed tokens are deliberately absent, because their operators do not document them.** `anthropic-ai` and `claude-web`: Anthropic's crawler page names only `ClaudeBot`, `Claude-User` and `Claude-SearchBot`. `cohere-ai`: Cohere's own page says it runs no crawling bots "at this time" and names none. `Bytespider`: ByteDance publishes no crawler documentation, and the reference URL in its user agent is unreachable. `archive.org_bot`: the Internet Archive's help pages do not name it. `ia_archiver`: that token belongs to Alexa Internet, retired in 2022, so a clause for it could not fire. Adding any of them is a decision to drop this section's rule, not a detail.
- **robots.txt asks; a WAF custom rule refuses.** Every token in this group except `Google-Extended` is also matched by the custom rule `loremfile_legal_pages_ai_agents` (`08` §5.7, ADR-030), which answers `403` on the two paths. `tests/unit/test_legal_pages.py` keeps the two lists equal.
- **The limit.** RFC 9309: robots.txt is "not a form of access authorization". These groups ask; they cannot enforce (`13` §3b).
- **`Content-Signal` states what the content may be used for**: search, AI input and AI training are all allowed, which is what CC0 already grants. Syntax as contentsignals.org publishes it (read 2026-09-21): a group member line before the group's rules, `key=yes|no` pairs separated by commas. It is in **both** groups because a crawler obeys only its most specific group (RFC 9309 §2.2.1); in the `*` group alone it would never reach the AI crawlers the named group matches. It grants nothing on the two disallowed paths: a signal is about use, and those paths are not to be fetched at all.

## 7. `sitemap.xml`

**Every discovery file carries `X-Robots-Tag: noindex`, and that is not a bug to fix.**
The `files_headers` rule matches any path containing a dot, so `sitemap.xml`,
`robots.txt`, `llms.txt`, `manifest.json`, `search-index.json`, `sha256sums.txt`,
`formats.json` and `security.txt` all receive it alongside the fixtures. It looks alarming
next to a Search Console error and it is the wrong suspect: Google's own sitemap
troubleshooting lists robots.txt blocking, manual actions, 404s, server errors and low
crawl demand as the causes of "Couldn't fetch" — `noindex` is not among them, and a
`noindex` sitemap is still fetched and read.

**The observation that prompted this (2026-09-17).** A Search Console submission reported
"Couldn't fetch" on a property verified minutes earlier, while the file served 200 to
Googlebot with 92 URLs. **Decision: no header change**; re-check after a few days, because
a just-verified property commonly reports that and resolves itself. This is written down
so the rule is not "fixed" later on a theory the documentation does not support — changing
`files_headers` to carve out the discovery files would alter the headers on every fixture
path, which is a real risk taken against an imagined cause.

**The decision stands after 2026-09-21.** Four display assets — `favicon.ico`, `apple-touch-icon.png`, `/assets/og.png`, `/assets/mark.svg` — were taken out of the noindex rule that day (`08` §5.3), because they exist to be *shown* by search engines and social platforms. That is not precedent for the discovery files: a sitemap does not need to be indexable to be fetched, and nothing in Google's documentation says otherwise.


Lists the home page, every format page, docs pages, legal pages **except `/legal/imprint` and `/legal/privacy`**, and the changelog. Does not list raw fixtures. `lastmod` = the committer date of the built commit (`07` §4), never the clock. Under 50 MB / 50,000 URLs, so a single file suffices.

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

Deployed copy of the JSON Schema (§1.4). `application/schema+json`, immutable cache headers.

## 10. Structured data on pages

JSON-LD per page type (single source of truth; `07` §3 refers here): home → `WebSite` + `SoftwareSourceCode` (pointing at the repository); format page → `Dataset` (`name`, `description`, `license: CC0`, `distribution` with `contentUrl` and `encodingFormat` per active fixture, `isAccessibleForFree: true`) + `BreadcrumbList`; docs and legal pages → `TechArticle` + `BreadcrumbList`, **except `/legal/imprint` and `/legal/privacy`, which carry no JSON-LD at all** (ADR-028). No `Organization` node.

## 11. Agent discovery

Four static standards, checked by Cloudflare's agent-readiness scanner. None of them lists or links either legal page, and `site build` refuses one that does (`site/checks.py`).

- **`Content-Signal`** in robots.txt (§6).
- **`Link` on every page** (RFC 8288), set by the `site_pages_headers` rule: `</llms.txt>; rel="describedby", </.well-known/api-catalog>; rel="api-catalog"`. Registered relation types only — `sitemap` is not in the IANA registry, RFC 8288 requires an unregistered type to be a URI, and robots.txt already names the sitemap. The same rule matches `/.well-known/api-catalog`, because RFC 9727 §2 requires its `HEAD` to carry the relation.
- **`/.well-known/api-catalog`** (RFC 9727), served as `application/linkset+json; profile="https://www.rfc-editor.org/info/rfc9727"` — the key has no extension, so `routes.content_type` names it rather than defaulting to HTML. One linkset entry per data file an agent can use: `manifest.json` with its schema as `service-desc`, `sha256sums.txt`, and every `{format}/index.json`, each with `llms.txt` as `service-doc`. A per-format index has no `service-desc`: it lacks the manifest's `formats` array, so the manifest schema does not describe it.
- **`/.well-known/agent-skills/index.json`** (Agent Skills Discovery v0.2.0) listing one skill, `find-and-verify-fixtures` (`site/agent-skills/`): find a fixture by format, fetch it, verify it against the manifest hash. The index carries `$schema`, and the skill entry's `digest` is the SHA-256 of the `SKILL.md` bytes, computed at build.
