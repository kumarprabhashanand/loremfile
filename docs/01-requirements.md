# 01 — Requirements

Each requirement has an ID, a MUST/SHOULD/MAY level, and acceptance criteria that a test or a checklist can verify. Tests referencing a requirement are named in `12-testing.md`.

## A. Functional

| ID | Level | Requirement | Acceptance criteria |
|---|---|---|---|
| REQ-01 | MUST | Every fixture is reachable at `https://loremfile.dev/{format}/{name}` with GET and HEAD. | `verify_live.py` HEADs every manifest path → 200; GET of a sample → bytes hash equals manifest. |
| REQ-02 | MUST | Published paths are immutable: bytes, hash and path never change after publication. Fixes are published under new names. | CI lock check fails any PR that modifies an existing manifest entry's `sha256`, `bytes`, `mime` or removes it. |
| REQ-03 | MUST | Every fixture response carries the exact `Content-Type` from the catalog, `Cache-Control: public, max-age=31536000, immutable, no-transform`, `Accept-Ranges: bytes`, `X-Content-Type-Options: nosniff`, `Cross-Origin-Resource-Policy: cross-origin`, and `Access-Control-Allow-Origin: *` whenever the request carries an `Origin` header. | Header contract check (`verify-live`, wrapped by `tests/live/test_headers.py`) passes for the smallest P1 fixture of each format. |
| REQ-04 | MUST | Byte-range requests work (`Range: bytes=0-99` → 206 with correct `Content-Range`). | Live test on `bin/10mb.bin` and `mp4/720p-5s.mp4`. |
| REQ-05 | MUST | CORS preflight (`OPTIONS` with `Origin` and `Access-Control-Request-Method: GET`) succeeds for any origin; `Content-Length`, `Content-Range`, `Content-Type`, `Content-Disposition`, `ETag`, `Accept-Ranges`, `Last-Modified` are exposed (the list in `03` §5). | Live test asserts headers on OPTIONS and GET with `Origin: https://example.org`. |
| REQ-06 | MUST | `GET /manifest.json` returns the manifest described in `04-manifest-and-discovery.md`, valid against `schema/manifest-v1.json`, listing every published fixture. | Schema validation in CI; live check that count equals committed manifest. |
| REQ-07 | MUST | `GET /sha256sums.txt` is usable with `sha256sum -c` after downloading files into matching relative paths. | CI runs `sha256sum -c` on generated files. |
| REQ-08 | MUST | `GET /` serves the website home page; `GET /{format}` serves a page listing that format's fixtures with copyable URLs, sizes and properties. | Live check: 200, `text/html`, contains each fixture path. |
| REQ-09 | MUST | `GET /llms.txt` and `GET /llms-full.txt` exist and follow the llmstxt.org layout. | Live check 200, `text/plain`. |
| REQ-10 | MUST | `GET /{format}/index.json` returns that format's manifest subset. | Live check for every format. |
| REQ-11 | MUST | Every fixture's actual properties match the catalog's expectations (page count, dimensions, duration, rows, encoding, byte size). | Validators run in CI; failure blocks merge. |
| REQ-12 | MUST | Size-named fixtures follow the naming convention: `Nkb/Nmb` decimal, `Nkib/Nmib` binary; files in `bin/` and `txt/lorem-*` are exact; all others are within ±5 % of nominal. `-plus-1` / `-minus-1` variants are exactly nominal ±1 byte. | Validator asserts exactness class from catalog. |
| REQ-13 | MUST | All fixtures are synthetic: no third-party copyrighted content, no real personal data, no private keys, no native executables, macros or script-bearing documents, no hostile payloads (`13-legal-and-policy.md` §5 defines the terms; `js/hello-console.js` and `wasm/minimal-add.wasm` are inert samples, not executables). | Content policy checklist in PR template; `validators/policy.py` in every build plus `tests/integration/test_policy_full.py` over all generated files. |
| REQ-14 | SHOULD | `www.loremfile.dev` redirects (301) to the apex with the same path. | Live check. |
| REQ-15 | SHOULD | Unknown paths return 404 quickly; Cloudflare caches the 404 for its 3-minute default. | Live check `GET /nope` → 404 within 1 s; M2.4 probe observes `cf-cache-status: HIT` on a repeated 404. |
| REQ-16 | MAY | Requests with `?download` … (deferred to Phase 3; see roadmap). | — |

## B. Non-functional

| ID | Level | Requirement | Acceptance criteria |
|---|---|---|---|
| REQ-20 | MUST | No origin server, no database, no runtime code path that writes. | Architecture review; `infra/` contains no Worker in Phase 1. |
| REQ-21 | MUST | Monthly infrastructure cost stays within Cloudflare free tiers at expected load. Because the Free plan has no usage-billing notification, the control is an automated daily read of R2 operations (`health.yml`, GraphQL Analytics) that opens a `cost` issue when month-to-date Class B operations exceed 5 M, plus a monthly billing review. | `health.yml` cost step green; `cost` issue opened when the threshold is crossed (tested with a lowered threshold once in M5). |
| REQ-22 | MUST | p50 time-to-first-byte for a cached fixture < 100 ms from a major region; aggregate cache hit ratio ≥ 95 % after warm-up (measured zone-wide, since each embedding origin has its own cache entry). | Cloudflare analytics; monthly review. |
| REQ-23 | MUST | Largest single fixture ≤ 100 MB (bandwidth-amplification cap) and ≤ 512 MB (Cloudflare cacheable-size limit on Free). | Validator enforces `bytes ≤ 100_000_000` unless the catalog entry sets `allow_large: true` (never set in P1; requires an ADR). |
| REQ-24 | MUST | Total bucket storage ≤ 8 GB (80 % of the 10 GB free tier). | CI sums manifest bytes and fails above 8 GB. |
| REQ-25 | MUST | Generation is reproducible: same catalog + same toolchain image digest → identical bytes. | Monthly determinism audit regenerates all P1 fixtures and reports drift (warning, not blocker). |
| REQ-26 | MUST | All secrets are scoped to the minimum resource and rotated at least every 180 days. | Token inventory in `10-security.md`; runbook rotation task. |
| REQ-27 | MUST | Daily automated health check opens a GitHub issue on failure and closes it on recovery, and keeps running without human activity (GitHub disables scheduled workflows in public repositories after 60 days without repository activity; the weekly ops-log commit that `health.yml` pushes to the unprotected `ops-log` branch is the keep-alive). | `health.yml` run with `inject_failure=<path>` opens the issue; the next clean run closes it (`12` §5); a Monday run adds a line to `ops-log.md` on the `ops-log` branch. |
| REQ-28 | MUST | Accessibility of the site: WCAG 2.1 AA for the pages (contrast, keyboard, labels, no JS required for core content). | Lighthouse accessibility ≥ 95; manual keyboard pass. |
| REQ-29 | SHOULD | Site pages score ≥ 95 in Lighthouse performance and SEO on mobile. | Lighthouse run in CI (informational). |
| REQ-30 | MUST | The website and fixtures load without third-party requests (no external fonts, scripts, analytics beacons). | CSP with `default-src 'self'`; CI scans built HTML for external URLs other than documented links. |
| REQ-31 | MUST | The repository can rebuild the entire published set from source plus a copy of published bytes (GitHub Release archives), even if Cloudflare is lost. | Restore drill in runbook (`11-operations-runbook.md` §7.6) executed once before launch. |

## C. Out of scope for v1 (recorded so nobody builds them by accident)

Uploads, auth, comments, rate-limit exemptions, custom 404 page, `?download` toggles, random-fixture endpoint, exact-size dynamic endpoint, MCP server, HEIC/HEVC/AV1 media, ODF documents, hostile fixtures. All appear in `14-roadmap-and-extensions.md` with designs.
