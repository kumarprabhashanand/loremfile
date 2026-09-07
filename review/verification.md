# Independent verification of the review fixes (2026-09-07)

Scope: `README.md`, `REVIEW.md`, `docs/00`–`docs/19` (read in full), `review/reviewer-a-implementer.md` (85 findings, 28 questions) and `review/reviewer-b-principal.md` (A-/X- vendor items, B-1…19, C-1…14, D-1…9, E-1…22, 13 questions). Line numbers are `cat -n` of the current files. No file under `docs/` was modified; scratch scripts ran from `/tmp`.

## Executive summary

- **Reviewer A (85 findings): 82 CLOSED, 0 ANSWERED, 3 PARTIAL (#13, #46, #64), 0 OPEN.** All three blockers (#1–#3) are closed by the `build --new` / `build --missing-in-bucket` selection rule (ADR-021) and the `infra.yml` workflow (ADR-022).
- **Reviewer B (90 items: 26 A-/X-, 19 B-, 14 C-, 9 D-, 22 E-): 74 CLOSED, 1 ANSWERED (D-4), 15 PARTIAL, 0 OPEN.** Every WRONG vendor fact (query-string cache key, purge limit, billing alert, 60-day schedule rule, `contains()`, verified-creator action) is corrected at its primary location; the PARTIALs are stale sentences left behind in secondary locations.
- **All 41 questions (A1–A28, B1–B13) have a recorded answer in `docs/18` §"Answers…" (18:45–72, 18:78–90)**; two answers are inconsistent with the docs (B9 "≈ 150" vs the actual 229-file launch list; the older Q&A block 18:34/18:37 still carries pre-fix statements).
- **New contradictions introduced by the edits: 13 substantive (1 High, 1 Major, 11 Medium) plus 15 nits (Table 4).** The worst: `docs/08` §9 still contains the *old* "cannot ignore query strings / cannot purge by prefix" list directly under the corrected one (08:279); the launch set in `05` §9 is 229 files, not "≈ 150" as stated in six places; the closed `defect` enum in `04` §1.3 makes the validator reject `edge/pdf-truncated-60pct.pdf` and `edge/exe-header-with-txt-extension.txt`; bucket locks were added without re-checking the takedown ordering, the `--restore` overwrite path and the M2.4 "locked prefix refuses overwrite" probe.
- **Verdict: implementable end to end after the Table 4 fixes (each is a local edit; none changes the architecture).** As it stands, an implementer would (a) be misled by 08:279, 19:19, 19:45, 18:34, 18:37, (b) scope M3 for 150 files and find 229, (c) fail CI on two edge fixtures if the `04` §1.3 enum is implemented literally, and (d) hit R2 lock refusals in three documented procedures.
- Naming grammar: 0 violations among the ~600 fixture names in `docs/05`; every `05` §9 launch fixture resolves to a `05` §3 row. JSON: 11 of 12 `docs/08` snippets valid; `r2-locks.json` example is invalid as written (comment inside JSON).

## Table 1 — Reviewer A findings #1–85

| # | Status | Evidence (file:line) | Note |
|---|---|---|---|
| 1 | CLOSED | 06:125–132; 09:75, 09:121–123; 02:73–78; 16:102–105 | `build --new` on PRs (paths absent from `origin/main:manifest.json`), `build --missing-in-bucket` on deploy, author commits the manifest, CI `manifest check` verifies (ADR-021) |
| 2 | CLOSED | 06:155; 09:123; 12:22; 09:234 | Deploy never runs `manifest update`; `generated_at`/`toolchain_image` excluded from the lock; the digest-bump PR updates them |
| 3 | CLOSED | 09:144–179; 06:203; 15:38–39; 16:107–110 | `infra.yml` `apply`/`probe` modes; `probe --down` deletes `_probe/*`; tokens never leave GitHub (ADR-022) |
| 4 | CLOSED | 05:254–255 | Explicit `depends_on` per truncation and mismatch fixture |
| 5 | CLOSED | 05:294–312 | §6 `fit()` recipe table covers every size-named fixture (checked one by one); non-convergence fails the build |
| 6 | CLOSED | 05:18–34 | Seeds `loremfile:dataset:*`, word lists in `data/wordlists/`, prefix property, `bio` Latin-1-safe |
| 7 | CLOSED | 05:314–318 | Per-script pseudo-text from character inventories; no third-party text |
| 8 | CLOSED | 06:64–92; 06:101 | Full YAML schema (`allow_large`, `status`/`removed`, `notes`, `policy_exceptions`, `edge`); `parallel_safe` is a decorator argument |
| 9 | CLOSED | 04:110, 04:112–120 | `if/then` branch; exact tombstone field list |
| 10 | CLOSED | 04:70; 06:153; 09:270 | Props frozen (compared only when bytes differ); patch releases exclude props |
| 11 | CLOSED | 06:108, 06:163 | `ctx.dependency()` downloads published bytes, hash-checked, never regenerates |
| 12 | CLOSED | 02:111; 08:18, 08:108, 08:121, 08:158; 16:58; 19:21 | 5 used (+1 optional) stated consistently; "6 phase files" = §5.1–5.6 |
| 13 | PARTIAL | 05:12, 05:290; 04:20; 06:235; 16:118 | 417 / ≈ 1.06 GB consistent and matches my own recount of §3 (417). Still stale: 04:135 `formats.json` example `"count": 14` for pdf (18 P1 rows, 12 launch rows); §5 family split says web 14 / data 81, rows give web 15 / data 80 (total unchanged) |
| 14 | CLOSED | 05:233, 05:286 | 335,572,633 bytes ≈ 336 MB |
| 15 | CLOSED | 10:55; 12:44; 11:112 | M5.4 / M5.3 / M5.5 |
| 16 | CLOSED | 09:9; 15:27, 15:44 | Job names; `build-and-validate` added to the ruleset in M3.1 |
| 17 | CLOSED | 09:129–136 | `git diff --name-only` with zero-SHA/`HEAD~1` fallback; `apply_infra` input |
| 18 | CLOSED | 06:132, 06:196; 15:44 | `--group` defined with the format mapping; M3 uses `--format` |
| 19 | CLOSED | 06:201–213; 09:255–262; 11:73 | Every flag defined; `--json` schema; takedown = `--apply-removals` in `deploy.yml` |
| 20 | CLOSED | 09:77; 12:30 | `pytest -q tests/integration` in `build-and-validate` |
| 21 | CLOSED | 12 §2–3; 01:11, 01:21; 04:110; 06:94, 06:247; 07:53; 15:28, 15:36, 15:66 | Every `tests/…` path in the set matches `12` (grep of all 21 files) |
| 22 | CLOSED | 05:13; 06:143; 05:34 | Loader appends `utf-8`; explicit override list; `bio` encodable in ISO-8859-1/Windows-1252 |
| 23 | CLOSED | 04:106; 06:92 | Closed enum with per-value validator assertion. The new text contradicts two catalogued fixtures — Table 4 #8–#9 |
| 24 | CLOSED | 03:13; 04:61; 06:94; 15:28 | HLS grammar exception; `filename`/`ext` from the last segment |
| 25 | CLOSED | 05:198, 05:344; 18:59 | `rss2-feed.xml`; no `rss-2.0` left (grep) |
| 26 | CLOSED | 06:110–111; 12:18 | Patched RNG/clock; per-library notes; fixed cert serial/subject/validity; run-twice tests name the affected paths |
| 27 | CLOSED | 07:42, 07:55–57; 15:65 | Agent drafts in `site/content/`; AI text acceptable; acceptance rule and word count |
| 28 | CLOSED | 07:7–22; 13:16–22 | Source per page; licence page text |
| 29 | CLOSED | 09:11, 09:25 | Repository variables, one scope |
| 30 | CLOSED | 01:13 | Seven exposed headers = 03:72 / 03:101 |
| 31 | CLOSED | 01:11 | "whenever the request carries an `Origin` header" |
| 32 | CLOSED | 01:14 | `schema/manifest-v1.json` |
| 33 | CLOSED | 02:55–58; 09:266 | Rows added; `schema/` never purged. (Two files added later, `search-index.json` and `site-manifest.json`, have no row — Table 4 #27) |
| 34 | CLOSED | 04:140 | Per-format values |
| 35 | CLOSED | 06:66; 05:324 | `family` field; mapping = `05` §5 columns |
| 36 | CLOSED | 04:204; 07:40 | Single source in `04` §10 |
| 37 | CLOSED | 05:182 | `control-characters.txt` `edge_case=true` (creates a schema conflict — Table 4 #10) |
| 38 | CLOSED | 05:225; 05:8 | Full path, standard seed |
| 39 | CLOSED | 05:200 | Explicit type list, "no float16" |
| 40 | CLOSED | 05:156, 05:158 | Sample rates and sources stated |
| 41 | CLOSED | 05:304, 05:296 | `fit` on a bitrate multiplier; a miss fails the build |
| 42 | CLOSED | 06:184 | `python-docx>=1.2`; TOC via raw `w:fldSimple` |
| 43 | CLOSED | 06:184; 12:19 | stdlib `zipfile`; `mimetype` first and stored |
| 44 | CLOSED | 06:184 | `Pillow>=11.3` |
| 45 | CLOSED | 06:184–185 | All libraries in `requirements.in`; host-only tools named |
| 46 | PARTIAL | 06:11–13, 06:25; 15:66 | `base.py`, `ci_summary.py`, `gh_issue.py`, `release.py` present and assigned. The same class of gap recurs: `python -m loremfile.ops_log` (09:211) is in no layout tree and no milestone |
| 47 | CLOSED | 06:189 | One line, full `ghcr.io/…@sha256:…` reference |
| 48 | CLOSED | 06:34, 06:200, 06:226 | `site serve` maps extensionless keys |
| 49 | CLOSED | 07:19, 07:33, 07:52 | `docs/index.html`, `legal/index.html` built; deeper trailing slashes 404 by design |
| 50 | CLOSED | 08:224–239; 15:38 | Endpoint / permission / 403-fallback table; M2.3 resolves |
| 51 | CLOSED | 08:36–38 | Hedges removed; dashboard equivalents kept |
| 52 | CLOSED | 08:42 | Verification moved to the M2.4 probe |
| 53 | CLOSED | 08:49; 12:53 | `python-requests/2.32` |
| 54 | CLOSED | 08:241; 06:206 | Warnings unless `--strict` |
| 55 | CLOSED | 08:272 | Readable settings audited; manual list explicit |
| 56 | CLOSED | 09:103 | No `id-token` |
| 57 | CLOSED | 09:228–229 | `git describe --tags --abbrev=0 <tag>^`; first release = snapshot |
| 58 | CLOSED | 09:229 | 1.5 GB parts + `parts.txt` |
| 59 | CLOSED | 09:63; 09:253 | `tools/check_lock.sh` |
| 60 | CLOSED | 09:266 | 100 operations per request |
| 61 | CLOSED | 10:73; 06:201 | `upload --restore` |
| 62 | CLOSED | README:65–66 | `THIRD_PARTY.md`, `docs/ops-log.md`, `docs/launch/` |
| 63 | CLOSED | 06:20, 06:112 | No `jar` |
| 64 | PARTIAL | 15:3 vs 15:19, 15:32, 15:42, 15:60, 15:69, 15:80, 15:102 | Re-stated as "≈ 100 (≈ 65 to launch, ≈ 35 P1b)", but M1–M5 = 8+6+40+8+6 = 68 (74 with M6); 68+35 = 103 (109 with M6). Still does not sum |
| 65 | CLOSED | 09:32–39; 15:26 | Action table with tags |
| 66 | CLOSED | 15:78 | M5.6 marked (O) |
| 67 | CLOSED | 06:185; 15:64; 12:51 | Host command given; informational (15:64 cites `07` §4 which has no Lighthouse text — Table 4 #24) |
| 68 | CLOSED | 18:31 | Rewritten as one sentence (a new self-correcting sentence appeared at 11:122 — Table 4 #11) |
| 69 | CLOSED | 06:205; 09:187; 01:37; 12:54 | `--inject-failure` / `inject_failure` |
| 70 | CLOSED | 06:110; 04:183 | Patches apply only inside `loremfile build` |
| 71 | CLOSED | 12:66 | Thin wrapper over `verify_live` |
| 72 | CLOSED | 03:114; 02:113; 19:19 | `Origin` in the cache key documented (19:19 also still says "includes the query string" — Table 4 #2) |
| 73 | CLOSED | 12:23; 15:66 | `test_upload_plan.py` at M4 |
| 74 | CLOSED | 06:142; 13:59; 05:255 | Whitelist by path; hash recorded in the manifest |
| 75 | CLOSED | 06:156; 07:52 | `site build` is the single writer |
| 76 | CLOSED | 08:42; 10:60 | r2.dev public URL verified disabled |
| 77 | CLOSED | 09:234, 09:41; 15:25 | `packages: write`; run once before M1.5 |
| 78 | CLOSED | 06:188; 15:24 | FTS5 and `zstandard` in M1.2's verify list |
| 79 | CLOSED | 05:322–323 | Popular list and related-format defaults |
| 80 | CLOSED | 09:9; 02:91 | CODEOWNERS explicitly informational |
| 81 | CLOSED | 03:53; 01:23; 15:39 | 3-minute default TTL; probed in M2.4 |
| 82 | CLOSED | 06:101 | Default `True`, decorator syntax |
| 83 | CLOSED | 09:219; 12:38; 01:11 | Smallest P1 fixture by bytes, ties by path |
| 84 | CLOSED | 07:32; 12:24 | Inlined `<svg>`; never `<object>`/`<iframe>`; unit test |
| 85 | CLOSED | 05:175 | Padding may be long, no width limit |

## Table 2 — Reviewer B findings

| ID | Status | Evidence | Note |
|---|---|---|---|
| A-1a | CLOSED | 02:111 | "5 used (2 URL rewrites + 3 response-header rules)" |
| A-2a | CLOSED | 02:34–40 | Phase order now redirect → sanitize → transform → ratelimit → managed WAF → cache |
| A-3a (WRONG) | PARTIAL | 02:40, 02:113; 03:14, 03:113; 08:168, 08:172, 08:276; 10:30; 16:65–68; 19:34 | Corrected at every primary location. Left behind: 08:279 (old "cannot do" list), 19:19 ("cache key includes the query string"), 19:45 ("query-string cache keys … are Enterprise features") — Table 4 #1–#3 |
| A-5 | CLOSED | 08:44, 08:41, 08:232 | "Dynamic Redirect" edit on T1; `[VERIFY name]`; `permission_groups` pasted in M0.4 |
| A-6a (COULD NOT VERIFY) | CLOSED | 16:11; 17:17; 15:39–40 | Kept as community-confirmed; M2.4/M2.5 + RISK-11 remain the gate (no change required) |
| A-6b | CLOSED | 03:53; 15:39 | 404 body declared non-contractual; TTL probed |
| A-6e / X17 | CLOSED | 03:114; 19:19; 02:113 | `Origin` in the cache key stated and costed |
| A-9a | CLOSED | 08:86, 08:89 | `cf_robots_variant: "off"`, `content_bots_protection: "disabled"` |
| A-9b (COULD NOT VERIFY) | CLOSED | 08:89, 08:229, 08:207 | `[VERIFY]` kept with dashboard fallback |
| A-10 | CLOSED | 10:35; 17:19 | Developer-Platform nuance added |
| A-11 (WRONG) | PARTIAL | 09:266; 08:276 | 100 per request and "purge by prefix … available" stated — but 08:279 still lists "purge by prefix/tag/hostname" as impossible (Table 4 #1) |
| A-13b | CLOSED | 03:85; 16:57 | Reworded; Chromium 40328564 and Mozilla 1582115 cited |
| X1 | CLOSED | 08:174, 08:236 | "endpoint and Free-plan availability verified"; `[VERIFY]` narrowed to the permission name |
| X4 (COULD NOT VERIFY) | CLOSED | 08:54–79, 08:81 | `browser_cache_ttl` removed; explanation kept |
| X5 (WRONG) | PARTIAL | 00:29; 01:31; 08:48; 10:30; 17:9; 19:30; 16:122–125 | Replaced by the automated check (ADR-025) everywhere except 18:34 ("alert at USD 5") — Table 4 #4 |
| X6 (WRONG) | CLOSED | 17:16; 09:207–217; 01:37; 11:45 | Monday ops-log commit as keep-alive; re-enable procedure |
| X7 | CLOSED | 09:229 | 1.5 GB split |
| X8 (WRONG) | CLOSED | 09:129–136 | `git diff --name-only` |
| X9 | CLOSED | 06:171, 06:176–178; 09:234 | `git gh ca-certificates curl` installed; smoke test |
| X10 (WRONG) | CLOSED | 09:12; 09:234 | `gh pr create` with `GITHUB_TOKEN`; no third-party action |
| X12 | CLOSED | 08:15, 08:212, 08:241, 08:272; 10:41, 10:61 | Normalization in desired state, audited, encoded-path probes |
| X13 | CLOSED | 01:23; 03:53; 19:34 | 3-minute 404 TTL in REQ-15 and the cost model |
| X14 | CLOSED | 08:36–38 | Hedges dropped; `wrangler@<pinned>` |
| X15 | CLOSED | 08 §7b; 16:112–115 | Bucket locks adopted (ADR-023) |
| X16 (COULD NOT VERIFY) | CLOSED | 08:45; 10:27, 10:36 | `[VERIFY]` in M2.4 `probe --down`; T3/T12 wording fixed |
| B-1 | PARTIAL | 08:168, 08:172; 16:65–68; 11 §7.4 (no strip-query redirect); 19:34–41 | Cache rule, ADR-013, T6, cost table redone; stale remnants at 08:279, 19:19, 19:45 |
| B-2 | PARTIAL | 05:326–349; 16:117–120; 15:42–58, 15:102–104; 15:3 | Launch set + P1b batches (M7) and M3 = 40 h + M7 = 35 h are within the recommended 60–90 h. But the "≈ 150" launch list actually contains 229 files (my count, Table 4 #6), and the 15:3 total still does not sum (Table 4 #7) |
| B-3 | CLOSED | 08:14, 08:39, 08:255–268; 16:112–115; 10:27, 10:36; 11:122; 02:49; 17:26 | Locks per format prefix; `_probe/` and site keys outside; takedown lifts one rule. Three consequences were not propagated — Table 4 #11–#13 |
| B-4 | CLOSED | 09:129–136 | (was Resolved) |
| B-5 | CLOSED | 06:170–178; 09:234; 15:24 | git/gh/ca-certificates/curl pinned; `git --version && gh --version` smoke test |
| B-6 | CLOSED | 09:207–217; 11:45; 17:16; 01:37; 16:124 | Heartbeat commit + re-enable procedure |
| B-7 | PARTIAL | 11:105; 17:25; 16:100; 18:12; 07:66 | Honest RTO, RISK-19, README pointer, Q-06 recommendation. Still stale: 18:37 "One working day to a new account or provider" — Table 4 #5 |
| B-8 | CLOSED | 06:108 | (was Resolved) |
| B-9 | PARTIAL | 11:72–74, 11:87, 11:110; 10:73 | `infra.yml` restore/audit/apply referenced in §7.1 step 4, §7.2, §7.3, §7.6. Not done: §7.1 step 3 (`missing_object`) and §7.7 still do not say "if `manifest check` fails with a hash diff under drift, use `infra.yml` → `restore`" |
| B-10 | CLOSED | 08:54–79, 08:81 | Removed |
| B-11 | CLOSED | 06:153; 12:22 | Props compared only when bytes changed; warning otherwise |
| B-12 | CLOSED | 06:171–175; 15:24 | apt packages pinned from `apt-versions.txt`; snapshot.debian.org fallback |
| B-13 | CLOSED | 09:229 | (was Resolved) |
| B-14 | CLOSED | 09:43, 09:47–49 | `ci.yml` no longer runs on push to `main` (comment at 09:75 is stale — Table 4 #26) |
| B-15 | CLOSED | 07:9, 07:52 | Slim `search-index.json`, fetched on first keystroke |
| B-16 | CLOSED | 02:34–40 | Phase order fixed |
| B-17 | CLOSED | 09:103 | (was Resolved) |
| B-18 | CLOSED | 08:36–41 | Pinned wrangler; rationale stated |
| B-19 | CLOSED | 06:110–111; 12:18 | Patch design, per-library RNG notes, run-twice parametrisation includes the named paths; 12:18 updated |
| C-1 | CLOSED | 08:241; 09:219; 12:42; 19:19; 01:32 | Warm-cache CORS probe; aggregate hit-ratio target; Tiered Cache required |
| C-2 | CLOSED | 08:15, 08:149–158, 08:212, 08:241, 08:272; 10:41, 10:61; 12:47; 15:39 | Normalization desired state + audit; encoded-path probes; optional response-type rule; T17 |
| C-3 | CLOSED | 03:83; 08:135, 08:155; 16:57; 12:46; 18:23 | Allow-list CSP byte-identical in 03/08 (×2); QA items added |
| C-4 | PARTIAL | 01:31; 08:46, 08:48; 09:204–206, 09:217; 16:122–125; 19:30, 19:34–41 | Automated analytics read (T4), `cost` issue at 5 M, arithmetic recomputed (I re-checked all four rows: consistent with the free tier subtracted), 404-path and 1,000-IP scenarios added. Stale: 18:34 "alert at USD 5" |
| C-5 | CLOSED | 09:292–294; 11:121–123; 13:67; 06:210; 18:24 | `release redact` mode; generator params removed; prefix purge (09:266) |
| C-6 | CLOSED | 10:27, 10:36, 10:40; 09:127, 09:219; 16:115 | T12 wording; T3 impact High without locks; `site-manifest.json` daily hash; locks. Separate tokens not adopted (not required) |
| C-7 | PARTIAL | 02:91; 09:9; 18:36 | 02 aligned ("informational"); 18:36 still describes the owner as CODEOWNER "(optional)" without saying it is unenforced |
| C-8 | CLOSED | 09:12; 09:234 | `gh pr create` |
| C-9 | CLOSED | 06:142; 15:55 | `on[a-z]+=`, `javascript:`, `<foreignObject`, `<set`/`<animate` on `href`, external hrefs; HTML checks with the `with-inline-js` exception |
| C-10 | CLOSED | 03:76 | Accept-and-document option taken; the affected paths are listed |
| C-11 | CLOSED | 03:83–89 | No change needed beyond C-3 |
| C-12 | CLOSED | 06:111; 05:244; 00:38; 13:54; 16:92–95 | `CN=fixture.example`, SAN `fixture.example`; "publicly derivable key" stated |
| C-13 | CLOSED | 09:85–87 | `new-fixtures` artefact only for same-repo PRs |
| C-14 | CLOSED | 01:21 | REQ-13 reworded; references `13` §5 |
| D-1 | PARTIAL | 11:72–74; 09:121; 09:172–173 | As B-9 |
| D-2 | PARTIAL | 11:23 (A), 11:24 (O); 08:46; 16:107–110 | T4 added; two weekly steps marked. Monthly items 11:30–34 (hardening spot-check, card, release check) and Email Routing/token creation are not marked O/A |
| D-3 | CLOSED | 11:118–124; 09:292–294; 13:67 | As C-5 |
| D-4 | ANSWERED | 11:110; 11:105 | Docs state that step 4's unknowns are exactly what M0.4 and M2 rehearse (durations recorded then) and make the throwaway-zone rehearsal optional (≈ USD 10); RTO restated |
| D-5 | PARTIAL | 10:79–87; 10:84; 11:57, 11:85 | Credential-loss table and day-181 consequence added; the `rotation-due` reminder is described in three places but `health.yml` (09:183–215) contains no step that produces it — Table 4 #18 |
| D-6 | CLOSED | 08:241; 09:217, 09:219; 12:42 | Encoded-path, site-integrity, usage read, warm-cache CORS probes; 429 retry |
| D-7 | CLOSED | 11:96 | HSTS/TLS-error consequence and cached-content note |
| D-8 | CLOSED | 11:129; 09:88–90 | "Inside the pinned toolchain image"; CI summary prints the entries to commit |
| D-9 | CLOSED | 09:204–214; 11:23 | `loremfile usage` + `ops_log` heartbeat (module missing from the layout — Table 4 #14) |
| E-1 | CLOSED | 02:111; 16:58; 19:21 | (was Resolved) |
| E-2 | PARTIAL | 04:20; 05:12, 05:290; 06:235; 19:17 | 417 / 1.06 GB everywhere except 19:17 "≈ 1.0 GB at launch" (and with the launch set now ≈ 620 MB, 19:17 and 15:73 "≈ 1 GB" are stale either way — Table 4 #20) |
| E-3 | CLOSED | 05:233, 05:286 | (was Resolved) |
| E-4 | CLOSED | 09:266 | (was Resolved) |
| E-5 | PARTIAL | 08:276 vs 08:279 | Corrected list written, old list not deleted (Table 4 #1) |
| E-6 | CLOSED | README:65–66 | (was Resolved) |
| E-7 | CLOSED | 08:215–222; 15:36 | `dns.json` defined; apply.py step 4 reads it |
| E-8 | CLOSED | 01:21; 04:110; 12:21–22, 12:31 | (was Resolved) |
| E-9 | CLOSED | 06:11–13, 06:129–132, 06:196–213; 09:75, 09:121–128, 09:173, 09:255–262; 10:69–73; 11:73, 11:110, 11:121–123 | (was Resolved) |
| E-10 | CLOSED | 10:73 | (was Resolved) |
| E-11 | CLOSED | 10:27, 10:36; 11:122; 09:259 | T2 deletes only tombstoned keys (lock lifted by owner) and `_probe/` |
| E-12 | CLOSED | 19:34, 19:38–39 | One convention (free tier subtracted), arithmetic consistent |
| E-13 | CLOSED | 09:12; 09:234 | As C-8 |
| E-14 | CLOSED | 02:34–40 | As B-16 |
| E-15 | PARTIAL | 15:3 | Was corrected to ≈ 64; re-edited to ≈ 100 / ≈ 65-to-launch which no longer sums (Table 4 #7) |
| E-16 | CLOSED | 08:174, 08:236; 08:232, 08:45, 08:81 | Tiered-cache tag narrowed; Dynamic Redirect name, T2 delete and `browser_cache_ttl` handled |
| E-17 | CLOSED | 03:85; 16:57 | Citations added |
| E-18 | CLOSED | 05:13; 06:143 | (was Resolved) |
| E-19 | CLOSED | 06:154; 04:112–120 | Mapping sentence added |
| E-20 | CLOSED | 12:18 | Patch-plus-grep design |
| E-21 | CLOSED | 10:69–73; 11:118–124 | (was Resolved) |
| E-22 | CLOSED | 19:19; 03:114 | (was Resolved) |

## Table 3 — Questions

| ID | Answered where | Consistent? |
|---|---|---|
| A1 | 18:45 → 06 §5, 09 §3.1–3.2, ADR-021 | Yes |
| A2 | 18:46 → 06:155 | Yes |
| A3 | 18:47 → 09 §3.2b, 15 M2.3–M2.4, ADR-022 | Yes |
| A4 | 18:48 → 05:254–255 | Yes |
| A5 | 18:49 → 05 §6 | Yes |
| A6 | 18:50 → 05 §2 | Yes |
| A7 | 18:51 → 05 §7 | Yes |
| A8 | 18:52 → 06:153, 09:270 | Yes (06:153 adds the "compare only when bytes changed" nuance; not contradictory) |
| A9 | 18:53 → 09:9 | Yes |
| A10 | 18:54 → 09:11, 09:25 | Yes |
| A11 | 18:55 → 09:228–229 | Yes |
| A12 | 18:56 → 06:110–111, 12:18 | Yes |
| A13 | 18:57 → 06:111 | Yes |
| A14 | 18:58 → 05:13 | Yes |
| A15 | 18:59 → 05:198 | Yes |
| A16 | 18:60 → 05:225 | Yes |
| A17 | 18:61 → 07 §5 | Yes |
| A18 | 18:62 → 07 §1, 13 §1.1 | Yes |
| A19 | 18:63 → 05 §8, 06:66–70 | Yes |
| A20 | 18:64 → 09:219, 12:38 | Yes |
| A21 | 18:65 → 01:37, 06:205, 12:54 | Yes |
| A22 | 18:66 → 06:185 | Yes |
| A23 | 18:67 → 15:5, README:71 | Yes |
| A24 | 18:68 → Q-14 | Yes |
| A25 | 18:69 → 05:182 | Yes, but see Table 4 #10 (schema conflict) |
| A26 | 18:70 → 05:200 | Yes |
| A27 | 18:71 → 09:259, 06:202–203 | Yes |
| A28 | 18:72 → 08:241, 06:206 | Yes |
| B1 | 18:78 → ADR-013, 08 §5.4, 03 §6 | Yes at those locations; contradicted by 08:279, 19:19, 19:45 |
| B2 | 18:79 → ADR-025, 19 §2, Q-20 | Yes; contradicted by 18:34 in the same file |
| B3 | 18:80 → ADR-023, 08 §7b, 11 §7.8, Q-16 | Yes |
| B4 | 18:81 → 03 §4.2, ADR-011, Q-17 | Yes |
| B5 | 18:82 → 08:46, ADR-022 | Yes |
| B6 | 18:83 → 01:32, 08:174 | Yes |
| B7 | 18:84 → 08:86 | Yes |
| B8 | 18:85 → 09 §10, 11 §7.8, 13 §7, Q-18 | Yes |
| B9 | 18:86 → ADR-024, 05 §9, Q-19 | **No** — the answer says "≈ 150" but `05` §9 lists 229 files (Table 4 #6) |
| B10 | 18:87 → 08:41 | Yes |
| B11 | 18:88 → 09:9, 02:91 | Yes (18:36 wording loose, C-7) |
| B12 | 18:89 → REQ-27, 11:45, RISK-10 | Yes |
| B13 | 18:90 → 11:105, RISK-19, Q-02 | Yes; contradicted by 18:37 in the same file |

## Table 4 — New contradictions or errors introduced by the edits

| # | Severity | File:line | Finding | Fix |
|---|---|---|---|---|
| 1 | High | 08:274–279 | §9 "What the Free plan cannot do" contains the corrected list (08:276) **and**, three lines later, the original list: "Regex in rules; ignoring query strings in the cache key; … purge by prefix/tag/hostname; …" (08:279). The two paragraphs contradict each other and ADR-013 / 09:266. | Delete 08:278–279. |
| 2 | Medium | 19:19 | "Note the cache key includes the query string and the `Origin` header" — contradicts 02:40, 03:113, 08:168, 16:67 (query string excluded). | "…the cache key includes the `Origin` header (query strings are excluded)…". |
| 3 | Medium | 19:45 | "the paid Cloudflare plans do not remove the constraints that matter here (query-string cache keys, regex in rules and >512 MB caching are Enterprise features)" — query-string handling is on all plans (A-3a). | Replace "query-string cache keys" with "custom cache-key headers/cookies". |
| 4 | Medium | 18:34 | "alert at USD 5" — the billing alert no longer exists in the design (ADR-025, 19:30). | "…`cost` issue at 5 M R2 reads month-to-date; runbook §7.4". |
| 5 | Medium | 18:37 | "What is the recovery time if Cloudflare disappears? One working day to a new account or provider" — contradicts the honest RTO at 11:105 / RISK-19 / ADR-020 (content and a mirror hostname in a day; `loremfile.dev` itself depends on Cloudflare support). | Restate per 11:105. |
| 6 | Major | 05:328 (also 05:12, 00:78, 15:44, 16:117–118, 18:86, REVIEW:20) | The launch set is described as "≈ 150 files" but `05` §9 enumerates **229** files (per row: pdf 12, png 8, jpg 9, other images 10, mp4 9, other video 12 incl. 6 HLS files, mp3 7, other audio 8, office 16, txt 16, web/text 16, csv-json 16, data 16, archives 17, fonts 4, bin 24, mail/cert/wasm 10, edge 19). M3's 40 h was sized against ~150; P1b (M7) is then 417 − 229 = 188, not ~267. | Either trim §9 to ~150 or change every "≈ 150" to "≈ 230" and re-check the M3/M7 split and the "≈ 620 MB" figure. |
| 7 | Minor | 15:3 | "Total ≈ 100 engineering hours (≈ 65 to launch, ≈ 35 for P1b)" — M1 8 + M2 6 + M3 40 + M4 8 + M5 6 = 68 to launch (74 incl. M6); total 103–109. (Regression of A#64 / E-15.) | State 68 (or 74) and 103 (or 109), or adjust the milestone estimates. |
| 8 | Medium | 04:106 vs 05:253 | `defect: truncated` is defined as "bytes == floor(0.5 × source bytes)", but `edge/pdf-truncated-60pct.pdf` is a 60 % truncation. A validator implemented from 04:106 rejects the fixture. | Define `truncated` with a `fraction` parameter in the `edge` block (default 0.5) or as "bytes == floor(f × source)" with `f` from the name. |
| 9 | Medium | 04:106 vs 05:255 | `defect: mismatched-extension` asserts "bytes equal the source fixture", but `edge/exe-header-with-txt-extension.txt` is `MZ` + `txt/lorem-1kb.txt` (not byte-equal to its source). Validator rejects it. | Give that fixture its own defect value (e.g. `magic-prefix`) or relax the assertion to "starts with the source's magic bytes". |
| 10 | Medium | 06:92 vs 04:69, 05:182 | `edge` (with `intended_format`, `defect` from the closed enum) "is required when `edge_case: true`", yet `txt/control-characters.txt` and `txt/nul-bytes.txt` are `edge_case: true` valid files under `txt/`; no enum value describes them (they are not defects). `catalog validate` would reject the two rows or force a fake defect. | Require `edge` only for fixtures under `edge/` (or add a `defect: unusual` value that asserts nothing). |
| 11 | Medium | 11:121–122 vs 09:126, 09:142, 08:268 | Takedown ordering: step 2 ends with "Merge", which triggers `deploy.yml`; its `upload --apply-removals` issues `DeleteObject` on a key still under an indefinite bucket lock → the delete is refused → the deploy job fails before `upload --site`/`purge` (09:142 "a failure at any step stops the job"). Step 3 then lifts the lock and says "run `deploy.yml`" as if it had not run. The step also contains a self-correcting narrative ("run `infra.yml` in `apply` mode? — no: run `deploy.yml`"), the pattern A#68 asked to remove, and says "purges its URL by prefix" while 09:259 says "purge the URL". | Reorder: lift the lock **before** merging (or make `--apply-removals` skip-and-warn on a lock refusal instead of failing); rewrite step 3 as one sentence. |
| 12 | Medium | 09:261, 11:73, 10:73 vs 08:268, 16:115 | `upload --restore` is "the one sanctioned overwrite" (writes where the live hash differs from the manifest) and §7.1 step 4 / §6 rely on it — but every `{format}/` prefix is now lock-protected, so the overwrite is refused at the storage layer. | State that a hash-differing restore requires the owner to lift the affected lock rule first (same ceremony as a takedown); `--restore` should report lock refusals explicitly. |
| 13 | Medium | 15:39 vs 06:203, 09:179, 08:268 | M2.4 must verify "a locked prefix refuses an overwrite", but `probe` may only write and delete under `_probe/`, which is outside every lock. Testing a locked prefix means writing a key such as `pdf/_probe` that can then **never** be deleted (indefinite lock), or lifting a lock — neither is documented. | Test lock behaviour on a dedicated locked prefix (e.g. `_locktest/` with its own rule, later left empty) or via the R2 API's lock GET only; say so in 15:39 and 06:203. |
| 14 | Minor | 09:211 vs 06:7–41, 15:66 | `python -m loremfile.ops_log --from usage.json --append docs/ops-log.md` uses a module that appears in no layout tree and no milestone. | Add `ops_log.py` to 06 §1 and to M4.3. |
| 15 | Minor | README:53 | Workflow list omits `infra.yml`, which 09 §3.2b, 11, 15, 16 depend on. | Add `infra.yml`. |
| 16 | Nit | 09:294 vs 09:154; 16:109 | §10 says the redact mode takes "input `path`" but the workflow input is `redact_path`; ADR-022 lists modes `audit, apply, probe, restore` (no `redact`). No milestone adds `redact` mode (M2.3 adds the workflow, M4.4 adds `restore`). | Align names; add `redact` to ADR-022 and to M4.4. |
| 17 | Minor | 09:16 vs 15:23, 09:206, 10:84 | Repository labels in 09 §1 lack `cost` and `rotation-due`, which `health.yml` and 15 M1.1 use. | Add both to 09:16. |
| 18 | Minor | 10:84, 11:57, 11:85 vs 09:183–215 | The `rotation-due` issue ("opened by `health.yml` 30 days before expiry, dates read from `docs/ops-log.md`") has no corresponding step in the `health.yml` listing, and the ops-log row format (11:136) has no column for token expiry dates. | Add a step and a column, or drop the claim. |
| 19 | Nit | 11:116 | §7.7 starts with "`manifest update` diff → …" but `deploy.yml` runs `manifest check` (09:123) and never `manifest update`. | Rename. |
| 20 | Nit | 19:17; 15:73; 06:239; 12:40 | "≈ 1.0 GB at launch" / "uploads ≈ 1 GB" vs the launch set's "≈ 620 MB" (05:328) and the full P1 1.06 GB. | Use 0.62 GB at launch, 1.06 GB after P1b. |
| 21 | Nit | 05:281–283 | Family split says web 14 / data 81; counting §3 rows gives web 15 (html 9, css 2, js 1, webmanifest 1, ipynb 1, har 1) / data 80. Total 417 unaffected. | Swap the two numbers. |
| 22 | Nit | 08:238 vs 15:14, 15:38; REVIEW:24 | The T4 "Account Analytics: Read **[VERIFY]**" tag is assigned to no milestone; REVIEW.md says every remaining `[VERIFY]` is resolved in M0.4/M2.3. | Add it to M0.4 (token creation) or M2.3. |
| 23 | Nit | 12:13 vs 15:36 | 12 says infra-file unit tests are due at M4; 15 makes `tests/unit/test_infra_files.py` the DoD of M2.1. | Say M2 in 12:13. |
| 24 | Nit | 15:64 | "Lighthouse (host, `07` §4)" — 07 §4 has no Lighthouse text; the command lives at 06:185. | Point at `06` §9. |
| 25 | Nit | 06:35 vs 05:317–318, 15:29 | Layout lists `data/wordlists/` only; `data/scripts/*.txt` and `data/emoji.txt` (05 §7, M1.7) are missing from the tree. | Add both. |
| 26 | Nit | 09:75 | Comment "on push to main this is normally empty" survives although `ci.yml` no longer runs on push to `main` (09:43, 09:47–49). | Delete the clause. |
| 27 | Nit | 02:47–59 vs 07:52, 09:127, 09:260 | `search-index.json` and `site-manifest.json` are uploaded with "cache-control per `02` §4" but have no row there. | Add rows (5-minute TTL). |
| 28 | Nit | 06:202 vs 06:203, 09:259 | `--apply-removals` is called "the only delete path in the tool" one line above `probe --down`, which also deletes. | "the only delete path besides `probe --down`". |
| 29 | Nit | 08:21; 10:16; 06:206 vs 09:134 | Inventory row still lists "Billing usage alert" unqualified; 10 §2 assets table names T1/T2 but not T4; `infra apply --dry-run` (09:134, 08:205) is not in the 06 §10 CLI table. | One-word edits. |
| 30 | Nit | 14:19; 08:158 | "8 of 10 would then be used" and "That makes 6 of the 10" presuppose the *optional* fourth header rule; 02:111 / 19:21 say 5 (6 with the option). | "7–8 of 10"; "6 of the 10 if the optional rule is added". |

Cross-checks that came out clean: transform-rule tally (5 + optional 1; six phase files); CSP string byte-identical at 03:83, 08:135, 08:155 (10:31 and 16:57 abbreviate it and point to 03 §4.2); cost-alert wording in 00/01/08/10/11/17/19 (only 18:34 stale); token inventory T1–T4 across 08/09/10/11; every `Mn.n`, `REQ-`, `ADR-`, `Q-`, `RISK-` referenced is defined (M7 included; REQ-17–19 intentionally unused); every `tests/…` path matches `12`; every CLI invocation is defined in 06 §10 except `infra apply --dry-run` (#29); all seven workflow names are defined in 09 and `infra.yml` modes used in 11/15/18 exist (#15–#16 aside).

## Naming-grammar check (docs/05 vs docs/03 §1)

Script: every backticked token in `docs/05` that carries an extension (with or without a `{format}/` prefix) tested against `^[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+)+$`, and `hls/…` tokens against `hls/{variant}/(index|master)\.m3u8` / `seg-[0-9]{3}\.ts`. Result: **597 names pass, 0 fixture-name violations.** The only regex hits are non-fixture tokens: MIME types (05:162, 05:205 ×2), `catalog/_tags.yaml` (05:269) and `src/loremfile/data/emoji.txt` (05:318). Shorthand tokens (`exif-orientation-1-640x480.jpg` + `-3-`/`-6-`/`-8-`, `lorem-1mb.txt.{bz2,xz,zst}`, `zero-byte.*`, `hls/720p-10s/*`) were expanded by hand and pass. `rss2-feed.xml` (05:198, 05:344) is valid; `rss-2.0-feed.xml` no longer appears anywhere.

## Launch set (docs/05 §9) vs catalog rows (docs/05 §3)

Every entry in §9 resolves to a §3 row of the named format (the script's four "misses" — `jpg/exif-orientation-6-640x480`, `bz2/lorem-1mb.txt.bz2`, `xz/…`, `zst/…` — are the shorthand rows above and exist). The `bin` row ("all 24 P1 rows of §3.10") and the `edge` row ("all seven `zero-byte.*`") match §3.10 (24) and 05:252 (7). **Mismatch found: the §9 total is 229 files, not "≈ 150"** (Table 4 #6).

## JSON validity (docs/08)

| Block | Result |
|---|---|
| 08:55 `zone-settings.json` | valid |
| 08:86 `bot-management.json` | valid |
| 08:98 §5.1 dynamic redirect | valid |
| 08:111 §5.2 URL rewrites | valid |
| 08:124 §5.3 response headers | valid |
| 08:152 optional fourth rule (bare object) | valid as an object |
| 08:163 §5.4 cache settings | valid |
| 08:179 §5.5 rate limit | valid |
| 08:192 §5.6 managed WAF | valid |
| 08:218 `dns.json` | valid |
| 08:248 `r2-cors.json` | valid (identical to 03:96–104) |
| 08:260 `r2-locks.json` | **invalid** — `/* … one entry for every format directory … */` inside the array; valid once the comment is removed. Since 08:257 calls this the committed file and `wrangler r2 bucket lock set --file` reads it, the example should not contain a comment. |

Also checked: 03:96 CORS and the four `docs/04` snippets (top-level, entry, tombstone, `formats.json`) are valid JSON.
