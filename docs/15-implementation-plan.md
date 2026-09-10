# 15 — Implementation Plan

Seven milestones. Each task has an ID, an owner type (**O** = owner/human must do it; **A** = engineer or agent), a definition of done (DoD), and an estimate in focused hours. Sums: M1 8 + M2 6 + M3 45 + M4 8 + M5 6 = **73 h to launch**, M6 6 h for the launch month, M7 30 h for the P1b batches — **≈ 110 h total** plus 2 owner hours. At the offered cadence (2 h/week for the first month, then 1 h/week) launch lands in roughly 14–18 weeks unless the owner grants longer sessions.

Assumed answers to open questions (see `18`): domain `loremfile.dev`; repo `github.com/<OWNER>/loremfile` under the owner's account; code MIT; fixtures CC0; no analytics; no AWS/Vercel; bucket location `auto`. **Placeholders:** `<OWNER>` and the contact mailbox can stay as placeholders through M1 and M3 (they live in `config.py`, the workflows, `security.txt` and `llms.txt` templates); M2 and M5 need the real values. M0 can happen in parallel with M1/M3 — only M2 and M5 wait for it.

## M0 — Owner setup (O, 1.75 h) — prerequisites for everything else

| ID | Task | DoD |
|---|---|---|
| M0.1 | Create/verify Cloudflare account with hardware-key 2FA and a payment method | `08` §2 steps 1–2 verified |
| M0.2 | Buy `loremfile.dev` via Cloudflare Registrar; enable DNSSEC | Zone exists; `dig +dnssec` shows RRSIG within a day |
| M0.3 | Create the GitHub repository `<OWNER>/loremfile` (public, empty) and give the engineer/agent admin | Agent can push |
| M0.4 | Enable R2; run `08` §2 steps 6–10b (bucket, apex custom domain, CORS, list the token permission groups, delete T3, create T1/T2/T4) and paste secrets/variables into the GitHub `production` environment. **Bucket lock rules moved to M2** — see `08` §2's note: before first publication a mistake must still be correctable, and that argument expires at the first deploy | **Partially complete (M3.6).** Done: `curl -sI https://loremfile.dev/` returns a Cloudflare 404, secrets present, apex and CORS applied. **Lock rules applied in M2.3 instead** (53 accepted, RISK-20 answered); the M4.4 gate still verifies the final set |
| M0.5 | Email Routing (`hello@`, `security@`, `dmarc@`) and notifications | Test mail received |
| M0.6 | ✅ **Done 2026-09-08.** The DPA forms part of the Self-Serve Subscription Agreement accepted at account creation, so it is in force; `13` §3a cites the governing version (v6.4, effective 2026-04-03) and records that Cloudflare exposes no separate acceptance artefact. **No acceptance date is published** — neither Art. 28 nor Art. 30(1) requires one, and the account creation date is personal metadata with no compliance benefit in a public repository | `13` §3a names the governing version and the basis; no placeholder left |

If the owner prefers, M0.4 can be executed by the agent in a session where the owner has logged in to wrangler (`npx wrangler login`), which avoids handling T3 manually.

## M1 — Repository skeleton and toolchain (A, 8 h)

| ID | Task | DoD |
|---|---|---|
| M1.1 | Initialise repo: layout from `README.md`, `pyproject.toml` (ruff, mypy, pytest), `LICENSE`, `LICENSES/CC0-1.0.txt`, `SECURITY.md`, `CONTRIBUTING.md`, `THIRD_PARTY.md`, `CODEOWNERS`, `AGENTS.md`, issue/PR templates, labels (`health`, `cost`, `rotation-due`, `determinism`, `infra-drift`, `fixture-request`, `security`, `good first fixture`), `dependabot.yml` | Files exist; `ruff` and `pytest` run (0 tests OK) |
| M1.2 | `tools/Dockerfile` (Python 3.12 slim + `git gh ca-certificates curl ffmpeg qpdf libavif-bin zstd xz-utils bzip2 sqlite3 fonts-dejavu-core`, every apt package pinned to the version recorded in `apt-versions.txt`), `requirements.in` → `requirements.lock` with hashes; build locally; record `apt-versions.txt`; verify `ffmpeg -encoders` includes libx264, libvpx, libopus, libvorbis, libmp3lame, aac, flac, theora, prores_ks and note libx265/libsvtav1 presence (**[VERIFY]**); verify SQLite has FTS5 and the `zstandard` package imports (**[VERIFY]**) | Image builds; versions recorded |
| M1.3 | `toolchain.yml` (`packages: write`) pushing to GHCR; run it once; write the full reference into `tools/TOOLCHAIN_DIGEST` | Image public on GHCR; digest file committed |
| M1.4 | Pin all actions to SHAs using the table in `09` §3 (`gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`) | No floating tags in workflows |
| M1.5 | `ci.yml` with the `lint-and-test` job only; branch ruleset requiring `lint-and-test`; environment `production`; repository variables | PR shows the required check |
| M1.6 | `config.py`, `catalog.py` (pydantic models + validation incl. the HLS grammar exception), `catalog/_tags.yaml`, `manifest.py` (schema incl. tombstones, lock rule, sums, formats.json), `schema/manifest-v1.json`, `tools/check_lock.sh`; unit tests | `tests/unit/test_catalog.py`, `test_manifest.py` green |
| M1.7 | `util/determinism.py` patches, `util/zipnorm.py`, `util/sizing.py` (`fit`), `util/lorem.py` + `data/scripts/*` + `data/emoji.txt`, `data/wordlists/*`, `datasets.py`, `util/ffmpeg.py`, `generators/base.py`; unit tests | Green |
| M1.8 | `gitleaks` scan of history; `.gitignore` for `build/` | Clean |

## M2 — Infrastructure as desired state (A, 6 h; needs M0)

| ID | Task | DoD |
|---|---|---|
| M2.1 | `infra/zone-settings.json`, `bot-management.json`, `rulesets/*.json`, `r2-cors.json`, `r2-cors.wrangler.json`, `r2-locks.json` (generated by `loremfile infra locks --write`), `dns.json` exactly as in `08` | `tests/unit/test_infra_files.py` green |
| M2.2 | `infra/cloudflare_api.py` (auth, retry, pagination), `apply.py`, `audit.py` with `--dry-run`; fake-API unit tests | Green |
| M2.3 | Add `infra.yml`; run it in `apply` mode (tokens stay in GitHub); resolve every **[VERIFY]** in `08`: permission names for bot management, DNSSEC, Single Redirects, URL normalization; the cache-key `exclude` literal; `fonts`/`speed_brain` setting IDs; the `http.response.content_type` rule; Free Managed Ruleset presence — record outcomes in `08` §6's table. **Also apply the R2 bucket lock rules and record whether the API accepts them (RISK-20)** | `infra.yml audit` exits 0; table updated. **Done 2026-09-09**: Free Managed Ruleset presence, `fonts`/`speed_brain`, and RISK-20 (53 rules accepted). Remaining: permission names, cache-key literal, `http.response.content_type`, URL normalization — the last verified independently by M2.4's encoded-path probe |
| M2.4 | Implement `loremfile probe` and run `infra.yml` in `probe` mode: `/` and `/_probe/` rewrites, the header rule classes, `%2E`-encoded paths, warm-cache CORS, CORS preflight, `www` redirect, query-string requests hitting the same cache entry (`?x=1` then `?x=2` → HIT), 404 caching (3-minute default TTL observed) and whether 1,000 probe 404s register as Class B operations in `loremfile usage` (**[VERIFY]**, `19` §3), rate limit (400-request burst → 429, recovery after 10 s), key `_probe/dir` coexisting with `_probe/dir/index.html`, and that T2 can delete under `_probe/` while the locked `_locktest/` prefix refuses overwrite and delete of `_locktest/probe` (written once, stays forever) | All checks pass; `_probe/*` deleted by `probe --down` |
| M2.5 | Write the M2 findings into `02` §4 (root/404 behaviour) and `08` §6 | Docs updated in the same PR |

## M3 — Generators, validators, the P1 launch set (A, ≈ 45 h; needs M1)

Scope for launch is the explicit list in `05` §9 (228 fixtures across every format family); the remaining 188 phase-1 rows (P1b) follow in M7 after launch. Implement in this order; each group is a PR with tests and catalog entries; the author runs `loremfile build --format <formats…> && loremfile validate --format <formats…> && loremfile manifest update` in the container and commits the manifest additions. M3.1's PR adds the `build-and-validate` job to `ci.yml`; it is added to the branch ruleset's **required** checks only once that job exists on `main`. Adding it earlier blocks every open pull request whose branch predates the job, because the check can never report on them — which is exactly what happened during M3.1 and had to be undone. Every generator family ships with its validator, its negative test and its determinism test in the same PR — the estimates below include that.

**Order changed after M3.6 — M2, then M4.3 and M4.4, come before the remaining format groups.** Finish the group in flight, then switch. Three reasons, heaviest first:

1. **The retention cliff makes per-merge deployment a correctness requirement, not an optimisation.** Fixtures marked `expected_drift` cannot be rebuilt byte for byte on other hardware (`06` §4), so between the pull request and the deploy their bytes exist only in the `carry-forward-fixtures` artifact — **90 days, measured on the artifacts themselves in M4.4** (`09` §3.1), not merely requested. At the M3 cadence the remaining groups would take longer than that, and when the artifact expires those manifest entries become unfulfillable: nothing to publish, and regeneration drifts. The fixtures would have to be re-catalogued at new paths.
2. **`upload.py` has to be designed around not regenerating those paths anyway** (`06` §5). Doing it now, with the failure fresh and five known paths to test against, beats retrofitting it in six weeks.
3. Every later M3 merge then deploys within hours on the same fleet, which is the steady state wanted regardless.

Fixtures going live before the website exists is fine: they carry `noindex`, nothing links to them, and nothing indexes them.

| ID | Group | Estimate |
|---|---|---|
| M3.1 | `datasets.py` (people/orders/products), `binary.py` (`bin/`), `text.py` (`txt/`, `md/`, `log/`, `ini/`) | 5 h |
| M3.2 | `data.py`: csv/tsv/json/ndjson/xml/yaml/toml/parquet/avro/arrow/sqlite/sql; `geo.py` | 10 h |
| M3.3 | `image.py` + `svg.py` (png/jpg/gif/webp/avif/bmp/tiff/ico/svg) | 5 h |
| M3.4 | `pdf.py` (fpdf2 + pypdf/qpdf validators, incl. encrypted determinism) | 4 h |
| M3.5 | `office.py` (docx/xlsx/pptx/rtf/epub) with `zipnorm` | 5 h |
| M3.6 | `media_video.py`, `media_audio.py`, `hls.py` (ffmpeg wrappers, ffprobe validators, sizing recipes) | 7 h |
| M3.7 | `archive.py` (zip/tar/gz/bz2/xz/zst/7z), `font.py`, `mail.py`, `calendar.py`, `cert.py`, `wasm.py`, `web.py` (html/css/js/webmanifest/srt/vtt/har/ipynb). **Also**: the first `.html` fixture is the first object that reaches rule H2's `.html and not ends_with("/index.html")` conjunct — staging verified only the `.svg`/`.xml` disjuncts (`09` §3.2). Verify that branch against the published object and record it there | 6 h |
| M3.8 | `edge.py` (truncations, zero-byte, mismatches, invalid syntax/encoding, hostile-name zip) + `policy.py` scan incl. the SVG/HTML event-handler checks | 3 h |
| M3.9 | Confirm the cumulative launch manifest (all M3.x PRs) is complete: `loremfile build --all --audit` inside the container regenerates everything within budget; `05` §5 updated with measured counts and bytes for the launch set | Audit shows 0 drift; `ci.yml` green ≤ 45 min |

Fallback if M3.9 exceeds the CI budget: matrix `--group`; if still over, defer the deferrable fixtures listed in `05` §5 to P1b.

## M4 — Website and discovery (A, 8 h; M4.1/M4.2 need M3.9 — **M4.3 and M4.4 are pulled ahead of the remaining M3 groups**, see M3)

| ID | Task | DoD |
|---|---|---|
| M4.1 | Templates, CSS (light/dark tokens), minimal JS (copy, filter); `site/build.py`, `site/serve.py`; discovery files; JSON-LD. **Also**: `health.yml`'s two absent steps — `loremfile site build` and the site-key half of `verify-live` — are added here (`09` §3.3); until then the daily run performs no defacement check, because hashing an empty `build/site/` would report a clean one for a site that does not exist. **Also**: the first extensionless key and the first `index.html` are the first objects that reach rule H3 at all, and the only ones that can exercise the `/index.html` **exclusion** in H1 and H2 — untested by staging because nothing it published could fire it (`09` §3.2). Verify all three branches against the published objects and record them there | `tests/site/*` green; Lighthouse (host command in `06` §9) a11y ≥ 95, informational; the three header branches verified |
| M4.2 | Content per `07` §5–§6: `site/content/formats/*.md` (agent-drafted, 120–250 words each for every format with a P1 fixture), `site/content/pages/*.md`, legal texts from `13` | Every page renders; facts checked against the catalog |
| M4.3 | `upload.py` (fixtures, removals, site, restore), `purge`, `verify_live.py` modes incl. `--inject-failure`, `usage.py`, `ops_log.py`, `tokens-due`, `gh_issue.py`, `release.py` (archive + redact); unit tests with fakes (`tests/unit/test_upload_plan.py` belongs here) | Green **Must not regenerate `expected_drift` paths** (`06` §4 and §5): they do not reproduce byte for byte between runs, so the deploy has to publish the bytes the manifest describes rather than rebuild them. |
| M4.4 | `deploy.yml`, `health.yml` (health, cost, rotation, heartbeat steps), `audit.yml`, `release.yml` complete; `infra.yml` gains `restore` and `redact` modes. **`deploy.yml` refuses to upload to any prefix without a lock rule** (`08` §2, `09` §3.2) | Workflows lint (`actionlint`, host); **bucket lock rules applied and verified against `infra/r2-locks.json`, and the ≈ 65-rule limit recorded (RISK-20)** — the deferral from M0.4 ends here, before the first deploy. **Split in two.** *First half, done*: `loremfile upload`, `r2.py`, `build --missing-in-bucket`, `deploy.yml` with both gates, and the launch-set reconciliation (161 + 5 + 62 = 228, `05` §9). `deploy.yml` ships dispatch-only with a `dry-run` mode; the `push` trigger follows the first green dry run (`09` §3.2). *Second half*: `health.yml`, `audit.yml` (`infra audit` does not exist yet), `release.yml`, and `infra.yml`'s `restore`/`redact` modes |

## M5 — First deploy and hardening (A, 6 h; needs M2, M4)

| ID | Task | DoD |
|---|---|---|
| M5.1 | Merge to `main` → `deploy.yml` uploads the ≈ 515 MB launch set, site, applies infra, smoke passes | Green run; https://loremfile.dev/ live |
| M5.2 | `verify-live --mode full` from a local machine | 0 failures |
| M5.3 | Manual QA checklist `12` §5 | All boxes ticked in an issue |
| M5.4 | Hardening checklist `10` §5 | All boxes ticked |
| M5.5 | Tag `v1.0.0`; `release.yml` produces the full snapshot archive (first release); restore drill `11` §7.6 steps 1–3 | Archive verified; time recorded |
| M5.6 (O) | Search Console + Bing Webmaster: verify domain (DNS TXT record supplied by the agent), submit sitemap | Submitted |

## M6 — Launch and first month (A + O, 6 h)

(M7 below runs after M6.1.)

| ID | Task | DoD |
|---|---|---|
| M6.1 | Draft posts (Show HN, dev.to article "sample files you can hotlink", r/webdev, r/QualityAssurance, a short X/Bluesky thread) in `docs/launch/`; owner publishes | Posted |
| M6.2 | README badge snippet and "Used by" section; answer the most common Stack Overflow questions **only if the owner wants to post** (agent drafts) | Drafts ready |
| M6.3 | Weekly sessions per runbook; first monthly review; record metrics | `ops-log.md` on the `ops-log` branch has 4 automated weekly lines and 1 monthly line |
| M6.4 | Retrospective: update `17-risks.md` likelihoods, pick Phase 2 batch 1, and answer **Q-22** (whether `MAX_FIXTURE_BYTES` should become 104,857,600) from six months of real request and cost data | Issue created; Q-22 answered or explicitly deferred again |

## First-session script for a coding agent

```
1. Read README.md, docs/00, 01, 02, 03, 06, 15 (this file); skim 08, 09.
2. Confirm M0 is complete (secrets present in GitHub; curl -sI https://loremfile.dev/ answers).
3. Execute M1.1 … M1.8 in order. Open one PR per task or per two related tasks. Never skip tests.
4. Stop when M1 is green in CI; write a short status comment in the tracking issue "Implementation status" listing done/next/blockers.
```

Tracking: one GitHub issue per milestone with the task table as checkboxes; the "Implementation status" issue pins the current milestone.

## M7 — P1b batches (A, ≈ 30 h spread over the first three months after launch)

Every catalog row marked phase 1 that is not in the `05` §9 launch list (188 files, ≈ 440 MB), in the family order of `05` §5, one PR per format family, each a minor release. Add new formats' bucket-lock rules (owner step) before their first deploy.
