# 12 — Testing and QA

## 1. Test pyramid

| Layer | Location | Runs | Purpose |
|---|---|---|---|
| Unit | `tests/unit/` | every PR (`lint-and-test`) | Generators deterministic, validators correct, catalog schema, manifest logic, uploader planning, zip normaliser, sizing helpers, CLI parsing |
| Integration | `tests/integration/` | every PR (`build-and-validate`) | Real generation in the toolchain image; validators on real outputs; manifest lock; site build; link check |
| Contract (live) | `tests/live/` + `verify-live` | after deploy (smoke), daily (daily), on demand (full) | Production behaves per `03-http-contract.md` |
| Infra audit | `infra audit` | after deploy, weekly | Cloudflare state equals desired state |
| Determinism audit | `build --all --audit` | monthly | Toolchain drift |

## 2. Unit tests (must exist before the milestone that builds the code under test is "done": M1 for catalog/manifest/utils, M2 for infra files, M3 for generators/validators, M4 for upload/site)

| Test | Asserts |
|---|---|
| `test_catalog.py` | Every YAML loads; names match grammar; unique; generator resolvable; params accepted by signature; `nominal_bytes` present for size classes; tags valid; `depends_on` acyclic and phase-consistent |
| `test_determinism.py` | For every P1 generator (parametrised, with small params for slow ones) two runs produce identical bytes; the parametrisation MUST include the paths whose libraries consume randomness or clocks internally — `pdf/a4-encrypted-1page.pdf`, `zip/aes256-password-loremfile.zip`, `avro/people-1000.avro`, `7z/3-text-files.7z`, `pem/self-signed-ed25519-cert.pem`, every docx/xlsx/pptx/epub — because Python-level patches of `os.urandom`/`random`/clocks do not reach C-level or OpenSSL RNGs and only the run-twice test proves determinism; a separate test greps generator modules for direct `random.`/`datetime.now` use |
| `test_zipnorm.py` | Normalising twice is idempotent; timestamps fixed; order sorted; EPUB `mimetype` first & stored; ZIP64 only when needed |
| `test_sizing.py` | Decimal/binary parsing of names; exact/boundary/approx classification; padding produces exact byte counts at word boundaries |
| `test_validators_negative.py` | Truncated/corrupted inputs fail the right validator; policy scan catches private keys, EICAR, `MZ`, ELF, external entities, `<script>` in SVG, PDF `/JavaScript`, `vbaProject.bin`, ratio > 1000 |
| `test_manifest.py` | JSON-Schema validation incl. tombstones; lock rule: changed hash/bytes/mime/props fails while description/tags/notes changes pass; removal without tombstone fails; `generated_at`/`toolchain_image` excluded from the lock; sorting/formatting stable; `sha256sums.txt` format; `formats.json`; totals cap |
| `test_upload_plan.py` (M4) | With a fake S3: new key → upload with right headers; same key same hash → skip; same key different hash → error; `--apply-removals` deletes only tombstoned keys; `probe --down` refuses keys outside `_probe/`; site keys content types; `--dry-run` writes nothing |
| `test_site_render.py` | Templates render with a small manifest; one H1; canonical; JSON-LD valid JSON; no external URLs beyond allow-list; no site key sits under a locked prefix (ADR-032); building twice from the same commit yields byte-identical output (integrity baseline); `mark.svg` is inlined, never referenced via `<object>`/`<iframe>` |
| `test_infra_files.py` | Rules JSON parse; refs unique; expressions contain no `matches` or `regex_replace` (Free plan); transform rule count ≤ 10; the two CORS files are equivalent |
| `test_cli.py` | Commands exit non-zero on failure; `--json` output schema |

## 3. Integration tests (`build-and-validate` job)

- `build --new`; run validators; `pytest tests/integration`; `manifest check`; build site; `tests/site/test_links.py` (every internal link resolves), `test_html.py` (parses, one H1, `lang`, title, description), `test_discovery.py` (llms.txt sections present, sitemap URLs exist, security.txt fields, robots).
- `tests/integration/test_policy_full.py`: policy scan over every generated file.
- `tests/integration/test_sizes.py`: sum of bytes ≤ 8 GB; every fixture ≤ 100 MB.

## 4. Live contract tests (`verify-live`)

**This table was written from estimates, and both kinds of number in it were wrong.** The times were an order of magnitude pessimistic; and the scope column describes more than `verify-live` does. So each mode now carries three things separately — what is specified, what is implemented, and what was measured — because **a time measured for a subset is not a time for the mode**, and a timeout sized against either the estimate or the subset is sized against nothing.

| Mode | Specified scope | Implemented (M4.4) | Measured against the 161 fixtures of the day (223 published since 2026-09-16) |
|---|---|---|---|
| `smoke` | `/`, `/pdf`, `/pdf/`, `/manifest.json` count == local, one fixture per format (the smallest P1 fixture by bytes, ties by path order): HEAD status/length/type + header contract; OPTIONS preflight; Range on two files; `www` redirect | HEAD + the full header contract **by value**, one fixture per format (50). **Not implemented:** the manifest count, OPTIONS preflight, Range, `www` redirect. With `--site-dir` (M4.1): `/`, a format page with and without its slash, and the legal pages | **9 s**, 50 checks (home connection). Estimate was "< 1 min" |
| `daily` | smoke + HEAD every fixture (parallel, ≤ 20 rps) + GET/hash for all < 1 MB + 5 % rotating sample of larger + site-key hashes against the checkout rebuild + expiry checks (RDAP, TLS, security.txt) | HEAD + header contract on every fixture, GET/hash of every fixture < 1 MB (117 of 161 then; 177 of 223 today), **sequential**. **Not implemented:** parallelism; the 5 % rotating sample — a fixture ≥ 1 MB is *never* hashed by `daily`; smoke's unimplemented checks. **Implemented 2026-09-15:** RDAP domain expiry (under 45 days), TLS certificate expiry (under 14 days), `security.txt` `Expires` (under 30 days), and with `--site-dir` every site key hashed against the rebuild plus the page header branches | **56 s** from a home connection; **21, 54, 70 and 99 s** on GitHub runners across the first four scheduled runs, and 31, 41, 74 s across the three control-drill dispatches — 278 checks. Estimate was "3–5 min". **No longer the scheduled check**: `health.yml` runs `full` since 2026-09-14, so the ≥ 1 MB gap in this row does not reach production monitoring |
| `full` | daily + GET/hash of **every** fixture (≈ 0.6 GB at launch, ≈ 1.1 GB after P1b) | HEAD + header contract + GET/hash of every fixture (322 checks), sequential; the RDAP and TLS expiry checks run here too; the other unimplemented checks of `smoke` and `daily` do not | **2 min 12 s**, 414 MB (home connection). Estimate was "15–30 min". **The daily health check since 2026-09-14.** On GitHub runners **unmeasured** until its first run there; estimated 50–235 s from the ~2.4× full/daily ratio at home applied to daily's 21–99 s on CI |

**What the unimplemented checks will add, so the next measurement is not a surprise.** The expiry checks, preflight, Range and redirect are a handful of requests — seconds. Site-key hashes are dozens of small files — seconds. The one that moves the number is `daily`'s **rotating sample of fixtures ≥ 1 MB**: 46 of 223, up to 100 MB each, so a day that samples a large video can add a download measured in tens of megabytes. `daily`'s runtime is expected to grow mainly from that, not from catalog size.

**Re-measure the whole table, not one row,** at two points: when the catalog reaches 228 fixtures, **and** when the unimplemented checks land — whichever comes first, and again at the other. Record all three columns each time. `health.yml` sizes its `verify-live` step timeout from the measured column, with the arithmetic in the workflow; when these numbers change, that timeout is checked against them in the same pull request. **The current bound is 10 minutes for `full`**: the CI estimate above scales to ~330 s at 228 fixtures, ~1.8× under the bound. The first CI run of `full` replaces the estimate with a measurement; if it exceeds 5 minutes, the bound is revisited.

Header contract checked per fixture (REQ-03/04/05): `content-type`, `content-length`, `content-disposition`, `cache-control`, `accept-ranges`, `x-content-type-options`, `cross-origin-resource-policy`, `timing-allow-origin`, `x-robots-tag`, `access-control-allow-origin` (with `Origin`), CSP `sandbox` on markup fixtures and **absent** on PDFs/media. **Values, not just presence** (M4.4): the first three come from object metadata frozen by the bucket lock, so a presence-only check would confirm the header exists while the contract was broken permanently; site pages have site CSP and `x-frame-options`, and no `x-robots-tag` — **except `/legal/imprint` and `/legal/privacy`, which must carry `x-robots-tag: noindex, nofollow, nosnippet`** (ADR-028). Checked against the published pages when M4.1 first publishes them. Also: encoded-path probes, warm-cache CORS probe, site-key integrity against a fresh `site build` of the checked-out commit; a 429 from our own rate limit is retried after 10 s.

## 5. Manual QA before launch (M5.3 checklist)

- [ ] Open 10 fixtures in Chrome, Firefox, Safari (PDF inline, MP4 plays with seeking, MP3 plays, PNG/WebP/AVIF render, SVG renders inert; `svg/with-embedded-png.svg` shows its embedded image; `html/with-inline-css.html` shows its styles; `html/with-inline-js.html` executes nothing).
- [x] `GET /html/basic%2Ehtml` carries the sandbox CSP (owner-verified 2026-09-17).
- [ ] `<video src="https://loremfile.dev/mp4/720p-5s.mp4" crossorigin>` on a page at another origin plays; `fetch()` from another origin returns bytes; `<img crossorigin>` draws to canvas without taint. **Browser-only.** The headers underneath were verified 2026-09-17: a Range request returns 206 with `content-range`, `access-control-allow-origin: *`, `cross-origin-resource-policy: cross-origin` and `timing-allow-origin: *`; what remains is whether browsers behave as those headers promise.
- [ ] Upload-limit test: `10mib.bin` accepted and `10mib-plus-1.bin` rejected by a sample app with a 10 MiB limit.
- [ ] `sha256sum -c` workflow from the docs works verbatim.
- [ ] Keyboard-only navigation of home and one format page; screen reader announces copy buttons; Lighthouse a11y ≥ 95.
- [ ] Mobile: no horizontal scroll on home/format/docs pages at 360 px width.
- [x] `curl -A ""`, `curl -A "python-requests/2.32"`, `curl -A "ClaudeBot/1.0"` and a plain `curl` all get 200 with no challenge (owner-verified 2026-09-17).
- [ ] REQ-27: run `health.yml` with `inject_failure=pdf/a4-3pages.pdf` → issue opened; run it again without → issue closed.
- [ ] Rate limit: 400 requests in 10 s from one IP → some 429s; after 10 s → 200 again.
- [ ] Search Console: sitemap submitted; no manual actions.

## 6. Definition of done (per fixture, per feature)

**Fixture**: catalog entry with description/tags/expect/size class; generator + validator; deterministic test; documented in `05`; CHANGELOG line; CI green; deployed; appears on the format page and in `llms-full.txt`.

**Feature/infra change**: requirement or ADR referenced in the PR; desired-state file updated; `infra audit` green after deploy; runbook updated if operations change; docs updated.

## 7. Test data hygiene

Tests never hit production except `tests/live/`, which is opt-in via `LOREMFILE_LIVE=1` and is a thin pytest wrapper that runs `verify_live` modes and asserts on the JSON (one implementation, two entry points). Unit tests use a fake S3 (`moto` is **not** used to keep the toolchain small; a 60-line in-memory fake in `tests/fakes/s3.py` suffices) and a fake Cloudflare API (`responses` library).
