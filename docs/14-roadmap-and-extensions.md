# 14 — Roadmap and Extensions

Phase 1 is the launch scope. Everything below is designed now so that Phase 1 decisions do not block it, but nothing here is built until Phase 1 is live and stable for four weeks.

## Phase 2 — Catalog depth (no infrastructure change)

All P2 fixtures in `05-fixture-catalog.md`, in this order: (1) remaining text encodings and unicode stress; (2) office extras (tracked changes, footnotes, data validation, hyperlinks, ODF via odfpy, legacy `.xls` only if a maintained writer exists); (3) media codecs (HEVC, AV1, ProRes, multi-bitrate HLS master, DASH `mpd`); (4) images (HEIC, 8000×8000, ICC profiles, CMYK TIFF); (5) data at 1 M rows (Parquet, CSV gz); (6) more edge cases (PDF xref/EOF defects). Each batch = one PR, one minor version.

Toolchain additions: `libheif-examples` (HEIC), confirm `libx265`/`libsvtav1` in Debian's ffmpeg, `odfpy`.

## Phase 3 — Dynamic endpoints on Worker routes (requires Workers Paid, USD 5/month, ADR-003)

A single Worker bound to **specific routes** so static traffic never touches it: `loremfile.dev/random/*`, `loremfile.dev/bytes/*`, `loremfile.dev/dl/*`, `loremfile.dev/404` (used only via a transform rule for unknown site paths, optional).

| Endpoint | Behaviour | Notes |
|---|---|---|
| `GET /random/{format}[?seed=…&tag=…&max_bytes=…]` | 302 to a fixture of that format chosen deterministically from `seed` (default: random) | Reads `manifest.json` from R2 with a 5-minute in-memory cache; `Cache-Control: no-store` on the redirect |
| `GET /bytes/{n}[?pattern=shake256|zeros|ones|incrementing]` | Exactly `n` bytes (1 ≤ n ≤ 100,000,000), `application/octet-stream`, `Content-Length: n`, supports `Range` | Implemented as an R2 range read of `bin/100mb.bin` (or the pattern files), so there is no CPU-bound generation; responses cacheable for a year with `Cache-Control: public, max-age=31536000, immutable` |
| `GET /dl/{format}/{name}` | Same object with `Content-Disposition: attachment; filename="{name}"` | Alternative without a Worker: a URL-rewrite rule `/dl/*` → `substring(path, 3)` plus a header rule keyed on `raw.http.request.uri.path` (`raw.` fields keep the pre-rewrite path). Free-plan compatible; costs 2 of the 10 transform rules (7–8 of 10 would then be used). Needs the same normalization/encoded-path review as the existing header rules (`10` T17). Prefer the rule-based version. |
| `GET /echo/*` | **Not** offered (httpbin exists; abuse surface) | |

Worker rules: input validation with explicit bounds; no fetch to third parties; `no-store` on errors; CPU < 10 ms per request; unit tests with Miniflare; the same `infra/` desired-state approach with a `worker/` directory and `wrangler deploy` in `deploy.yml` guarded by a `worker/` change filter. Cost model: 10 M requests/month included; if `/bytes/` becomes popular the cache absorbs it.

## Phase 3b — Machine interfaces

- **MCP server** `@loremfile/mcp` (npm, stdio): tools `list_formats`, `search_fixtures({format?, tags?, max_bytes?, text?})`, `get_fixture(path)` returning URL + props + sha256, `download(path, dest)`. Reads `manifest.json` (cached 1 h). Zero infrastructure. Publish under the same GitHub org; provenance via npm trusted publishing from `release.yml`.
- **CLI** `npx loremfile get pdf/a4-3pages.pdf [--verify]`, `npx loremfile search --format csv --tag encoding` — thin wrapper over the same manifest client.
- **Python client** `pip install loremfile` with `loremfile.get("pdf/a4-3pages.pdf", verify=True)` and pytest fixture `loremfile_file`.
- **OpenAPI 3.1 document** at `/openapi.json` describing the static paths generically (path templates) and the Phase 3 endpoints, for API tooling that expects it.

## Phase 4 — Unsafe fixtures on a separate domain (decision required, Q-08)

Purpose: security tooling needs EICAR, zip bombs, oversized headers, polyglots, XXE payloads, script-bearing PDFs/SVGs. These endanger the main domain's reputation, so they live on a **separate registrable domain** (e.g. `loremfile-unsafe.dev` or a `.wtf`/`.zone` domain), separate bucket, separate zone with the same infrastructure code parameterised, `robots.txt: Disallow: /`, an interstitial page, and a stricter policy review per fixture. Not started before month 6. Budget: USD 10–30/year for the domain.

## Phase 5 — Mirror and resilience (optional)

- Second bucket in another provider (Bunny Storage or Backblaze B2, roughly USD 1–2/month at 1 GB + modest egress) served at `mirror.loremfile.dev` or an entirely separate domain, synced by `release.yml`. Provides an off-Cloudflare live copy. Only if usage justifies the "never breaks" promise strengthening.
- Sigstore/cosign signatures for `manifest.json` and release archives (keyless via GitHub OIDC, free).

## Ideas explicitly rejected

| Idea | Why not |
|---|---|
| User uploads or "share a file" | Moderation, abuse, legal exposure; contradicts the no-write-path principle |
| Screenshots / URL-to-PDF / conversions | Compute, SSRF, abuse |
| Public API keys / tiers | Adds accounts and a database |
| Ads or sponsorship banners | The entire value is being the clean option; a "sponsored by" text line in the footer is acceptable if ever needed |
| Copying real-world sample media (Big Buck Bunny, etc.) | Licence bookkeeping; generated media is enough for tests |
| Hosting `.zip` of the whole catalog at a fixed URL | 1 GB object behind the cache limit; use GitHub Releases |
