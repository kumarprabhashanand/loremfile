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
| `test_site_render.py` | Templates render with a small manifest; one H1; canonical; JSON-LD valid JSON; no external URLs beyond allow-list; `pdf` and `pdf/index.html` outputs are byte-identical; building twice from the same commit yields byte-identical output (integrity baseline); `mark.svg` is inlined, never referenced via `<object>`/`<iframe>` |
| `test_infra_files.py` | Rules JSON parse; refs unique; expressions contain no `matches` or `regex_replace` (Free plan); transform rule count ≤ 10; the two CORS files are equivalent |
| `test_cli.py` | Commands exit non-zero on failure; `--json` output schema |

## 3. Integration tests (`build-and-validate` job)

- `build --new`; run validators; `pytest tests/integration`; `manifest check`; build site; `tests/site/test_links.py` (every internal link resolves), `test_html.py` (parses, one H1, `lang`, title, description), `test_discovery.py` (llms.txt sections present, sitemap URLs exist, security.txt fields, robots).
- `tests/integration/test_policy_full.py`: policy scan over every generated file.
- `tests/integration/test_sizes.py`: sum of bytes ≤ 8 GB; every fixture ≤ 100 MB.

## 4. Live contract tests (`verify-live`)

| Mode | Scope | Time |
|---|---|---|
| `smoke` | `/`, `/pdf`, `/pdf/`, `/manifest.json` count == local, one fixture per format (the smallest P1 fixture by bytes, ties by path order): HEAD status/length/type + header contract; OPTIONS preflight; Range on two files; `www` redirect | < 1 min |
| `daily` | smoke + HEAD every fixture (parallel, ≤ 20 rps) + GET/hash for all < 1 MB + 5 % rotating sample of larger + site-key hashes against the checkout rebuild + expiry checks (RDAP, TLS, security.txt) | ≈ 3–5 min at launch (228 files), ≈ 6–10 min at 416 files; `health.yml`'s `timeout-minutes: 30` is the hard ceiling and must be raised before the catalog outgrows it |
| `full` | daily + GET/hash of **every** fixture (≈ 0.6 GB at launch, ≈ 1.1 GB after P1b) | **Measured 2026-09-10: 2 min 12 s** for 161 fixtures / 414 MB, from a home connection, sequential — against an estimate of 15–30 min. The estimate was an order of magnitude high, and the consequence is worth acting on: `full` is cheap enough to run on any change worth checking, not only at M5.2. Re-measure when the catalog reaches 228 |

Header contract checked per fixture (REQ-03/04/05): `content-type`, `content-length`, `content-disposition`, `cache-control`, `accept-ranges`, `x-content-type-options`, `cross-origin-resource-policy`, `timing-allow-origin`, `x-robots-tag`, `access-control-allow-origin` (with `Origin`), CSP `sandbox` on markup fixtures and **absent** on PDFs/media. **Values, not just presence** (M4.4): the first three come from object metadata frozen by the bucket lock, so a presence-only check would confirm the header exists while the contract was broken permanently; site pages have site CSP and `x-frame-options`, and no `x-robots-tag`. Also: encoded-path probes, warm-cache CORS probe, site-key integrity against a fresh `site build` of the checked-out commit; a 429 from our own rate limit is retried after 10 s.

## 5. Manual QA before launch (M5.3 checklist)

- [ ] Open 10 fixtures in Chrome, Firefox, Safari (PDF inline, MP4 plays with seeking, MP3 plays, PNG/WebP/AVIF render, SVG renders inert; `svg/with-embedded-png.svg` shows its embedded image; `html/with-inline-css.html` shows its styles; `html/with-inline-js.html` executes nothing).
- [ ] `GET /html/basic%2Ehtml` carries the sandbox CSP.
- [ ] `<video src="https://loremfile.dev/mp4/720p-5s.mp4" crossorigin>` on a page at another origin plays; `fetch()` from another origin returns bytes; `<img crossorigin>` draws to canvas without taint.
- [ ] Upload-limit test: `10mib.bin` accepted and `10mib-plus-1.bin` rejected by a sample app with a 10 MiB limit.
- [ ] `sha256sum -c` workflow from the docs works verbatim.
- [ ] Keyboard-only navigation of home and one format page; screen reader announces copy buttons; Lighthouse a11y ≥ 95.
- [ ] Mobile: no horizontal scroll on home/format/docs pages at 360 px width.
- [ ] `curl -A ""` and `curl -A "python-requests/2.32"` and `curl -A "ClaudeBot/1.0"` all get 200 (no challenge).
- [ ] REQ-27: run `health.yml` with `inject_failure=pdf/a4-3pages.pdf` → issue opened; run it again without → issue closed.
- [ ] Rate limit: 400 requests in 10 s from one IP → some 429s; after 10 s → 200 again.
- [ ] Search Console: sitemap submitted; no manual actions.

## 6. Definition of done (per fixture, per feature)

**Fixture**: catalog entry with description/tags/expect/size class; generator + validator; deterministic test; documented in `05`; CHANGELOG line; CI green; deployed; appears on the format page and in `llms-full.txt`.

**Feature/infra change**: requirement or ADR referenced in the PR; desired-state file updated; `infra audit` green after deploy; runbook updated if operations change; docs updated.

## 7. Test data hygiene

Tests never hit production except `tests/live/`, which is opt-in via `LOREMFILE_LIVE=1` and is a thin pytest wrapper that runs `verify_live` modes and asserts on the JSON (one implementation, two entry points). Unit tests use a fake S3 (`moto` is **not** used to keep the toolchain small; a 60-line in-memory fake in `tests/fakes/s3.py` suffices) and a fake Cloudflare API (`responses` library).
