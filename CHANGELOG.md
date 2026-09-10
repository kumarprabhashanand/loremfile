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

### Added

- The specification (`docs/00`–`19`) and its three review passes (`review/`).
- Repository skeleton: packaging, licences, contributor and agent documentation,
  issue and pull request templates, Dependabot configuration (M1.1).
- Pinned toolchain image: `tools/Dockerfile`, `tools/apt-versions.txt`,
  `tools/requirements.in`, `tools/requirements.lock` (89 packages, hashed),
  `tools/smoke.sh` and `tools/licences.py` (M1.2).
- `.github/workflows/toolchain.yml` — builds the image, publishes it to GHCR, smoke-tests
  the pushed digest and uploads a provenance artifact; `tools/TOOLCHAIN_DIGEST` records
  the published reference (M1.3).
- `tests/unit/test_requirements_lock.py` — asserts the lock is installable under
  `pip install --require-hashes`.
- `src/loremfile/config.py`, `catalog.py`, `manifest.py`, `schema/manifest-v1.json`,
  `catalog/_tags.yaml` and `tools/check_lock.sh`; the `loremfile catalog validate` and
  `loremfile manifest check|update` commands (M1.6).
- `util/determinism.py`, `util/sizing.py`, `util/zipnorm.py`, `util/lorem.py`,
  `util/ffmpeg.py`, `datasets.py`, `generators/base.py`, the word lists, per-script
  character inventories and the emoji list (M1.7).

### Fixed

- The catalog loader appended `; charset=utf-8` only to `text/*`. `docs/06` §6 also
  requires it for `application/json`, `application/xml`, `application/yaml`,
  `application/toml`, `application/x-ndjson` and `application/geo+json`.
- `util/ffmpeg.run` placed output-only options before the input, which is invalid
  ffmpeg argument grammar and failed outright with `-f lavfi`.

- `tools/requirements.lock` left `pip` and `setuptools` unpinned, so the toolchain image
  could not be built at all (`pip install --require-hashes` refused it). Regenerated with
  `--allow-unsafe`; a unit test now checks the file itself.

### Added — `deploy.yml`, `loremfile upload`, and both gates (M4.4, first half)

- **`loremfile upload --fixtures | --apply-removals`**, with `--carry-forward <dir>` and
  `--dry-run`. `infra/r2.py` is the only place that addresses the bucket; the plan stays a
  pure function. A listing comes first so that only keys the bucket actually holds are
  HEADed — zero requests on a first deploy, one per published fixture thereafter, and a
  HEAD is unavoidable because a listing returns ETags rather than the `sha256` the
  manifest records.
- **`build --missing-in-bucket` implemented**, and it **never selects an `expected_drift`
  path**. On the deploy runner a rebuild of one of those is bytes the manifest does not
  describe, so building it would fail `manifest check` on a fixture the deploy was never
  going to upload. Without a listing the selection **refuses** rather than falling back to
  `--all`, which would rebuild the whole catalog on the deploy runner.
- **Every byte is hashed before it is published.** `verify_sources` refuses a source whose
  digest or length disagrees with the manifest. This is what makes the carry-forward
  download safe to do loosely: the artifact comes from a *different* workflow run and is
  untrusted input, so an artifact from the wrong run cannot pass and provenance is
  established by content rather than by a run id.
- **A published object with no `sha256` metadata now fails rather than skipping.**
  "Present" is not "correct"; without the metadata there is nothing to compare, and
  reporting it as a mismatch against an empty string named the wrong problem.
- **`deploy.yml`** carries both gates — no upload to a prefix without a lock rule, no
  regeneration of an `expected_drift` path — enforced inside `upload` rather than in YAML,
  so a local dry run gets them too.

**Deliberately not in it.** `site build`, `upload --site` and `purge --site` (the site is
M4.1); `loremfile infra audit` (never written — only `apply.py` landed in M2.2, and the
audit arrives with `audit.yml`); `-j 4` (`-j` is not implemented). Each is listed in
`docs/09` §3.2 with the milestone that adds it, rather than standing in the workflow as a
guaranteed red cross. `--force-site` was dropped from the CLI for the same reason: an
option that changes nothing is worse than an absent one.

**And the trigger, which is a judgement rather than a missing command.** `docs/09` §3.2
specifies `push: branches: [main]`, and that is the steady state. But the first run of this
workflow is also the first time `loremfile upload` has ever addressed a bucket, and its
writes land under **indefinite lock rules** — published, locked, permanent. A first
exercise that is also an irreversible one is the wrong order, which is the `release.py`
caveat again. So it ships dispatch-only with `mode` defaulting to **`dry-run`**: real
listing, real HEADs, real gate evaluation, real source hashing, no writes. The `push`
trigger is a three-line change once that run is green.

**The launch set reconciles, and is now checked rather than remembered.**

| Bucket | Count |
|---|---|
| Published in `manifest.json` | 161 |
| Catalogued, awaiting publication (the five `expected_drift` rows) | 5 |
| Still to catalogue: M3.7 + M3.8 | 62 |
| **Launch set (ADR-024)** | **228** |

`tests/unit/test_deploy_path.py` asserts it, with the 62 as a named constant an M3.7 or
M3.8 pull request must decrement. It is the one figure that cannot be derived from the
repository, so fixtures added without accounting for launch scope become a failing build
instead of a slow drift away from 228.

### Added — the daily missing-key series, before the baseline expires

The pre-launch period is the only one in which the missing-key rate is uncontaminated
background scanning, and it cannot be reconstructed later. `usage` now returns it and
`ops_log` commits it.

- `usage --daily-days N` (default 32) adds a **`daily`** array to the JSON document: per-day
  Class A, Class B and `GetObject`/`userError` counts. Month-to-date counters cannot express
  a rate — they are cumulative and reset at the month boundary.
- **Two API limits, read off the API's own refusals rather than off documentation**:
  retention **90 days** (*"cannot request data older than 12w6d"*) and a maximum window of
  **32 days** (*"cannot request a time range wider than 4w4d"*). Both are constants with a
  guard that refuses before the request is sent, so the caller learns which limit it crossed
  instead of receiving a 200 with an `errors` array. The guard ships with a negative control
  that it admits the windows it is meant to admit.
- `ops_log` writes **one row per day**, not one per week. Each weekly commit backfills the
  days in its report and **replaces** a date already present, so overlapping 32-day windows
  converge on one row per day rather than double-counting. A log written by the previous
  weekly-row code merges rather than breaking.
- The em-dash rule gains its negative control: a genuinely zero day must render `0`, so a
  formatter that rendered every cell as `—` can no longer pass the "absent is not zero" test.
- `docs/19` §3.2 records the baseline itself: **≈380–780 external missing-key reads a day**,
  bursty rather than smooth — one or two credential scans of 250–285 requests account for
  most of it, and between scans the rate falls to ≈0.1/min. The floor is **not** the daily
  average; quoting it as the baseline would understate by about a factor of three.
- `docs/19` §3.1 gains the calibration: the 2026-09-10 scanner ran at **≈2.3 req/s from one
  address**, under a tenth of the rate limit's 30 rps threshold, so **the limit never engaged
  and would not have**. Scenario 1 models a single IP sustaining the ceiling for thirty days;
  it is an **upper bound, not an expectation**, and that now rests on an observation.

### Verified — R2 counts a 404 as a Class B read; the cost model's premise holds

The measurement pre-registered in `docs/19` §3 was run attended, as a handshake with the
owner, on 2026-09-10. **Branch (a), on both instruments.**

- **1,000 unique missing paths produced exactly 1,000 `GetObject`/`userError` records.**
  Fired 09:17:29–09:18:40Z at 14.2 req/s; all 1,000 returned 404 and **none** were stopped
  by our own rate limit, so all 1,000 reached R2. The counter restricted to the burst
  window reads 1,000 on two reads three hours apart — attribution by dimension, not a delta
  against noise. Threshold was ≥ 900.
- **The billing side agrees.** The owner's R2 → Overview moved **1.89 k → 3.3 k**; the
  analytics Class B total moved **2,040 → 3,351** across the same span. Two independent
  consumption records agreeing on level and movement. RISK-22's residual is now
  **accepted-on-evidence** — and the section says in terms that "evidence" means two
  agreeing consumption records, **not an observed invoice**.
- **Two deviations, recorded rather than smoothed.** The baseline pair did not agree
  strictly (+1 over 10m42s, ≈0.1/min) and that was reported before firing, not after. The
  post-burst wait was ~3 hours rather than 10 minutes; that strengthens the result, because
  at that distance a lagging dashboard is no longer an available explanation for either a
  moving or a flat reading.
- **An unsolicited replication.** Thirty minutes after the burst, a credential scanner
  (single cloud host, `.env` / `phpinfo.php` / `firebase-adminsdk.json` paths, ~283
  requests, 282 misses) drove **273** further missing-key reads in two minutes. Nobody
  arranged it. `docs/19` §3's own vector arrived unprompted on a domain with no audience,
  and produced the same kind of record as the synthetic burst. Background rate outside the
  two events: ≈0.1 missing-key reads per minute. The bounding rule belongs to M4.4.
- `docs/19` gains **§3.1** with all six readings; RISK-22 records the premise and the
  residual. The scenario table is **unchanged** — it already assumed every request is a
  read, which is precisely what was confirmed.

**Verified list.** Now verified on evidence: ADR-013 (query-string cache key, `Age`-based),
404 caching, rate-limit enforcement at a single identity, and **R2 recording a missing-key
GET as a Class B operation, corroborated by the consumption counter**. Still **not**
verified: the 404 cache **duration** (a positive `Age` is age at sampling, not a TTL),
rate-limit behaviour across a split identity, and whether Cloudflare **bills** a recorded
`userError` GetObject — no API reports that, and the distinction between a recorded
operation and a billed one is kept rather than elided.

### Added — `gh_issue`, `ops_log`, `release` and `tokens-due` (M4.3 complete)

- `gh_issue.py`: de-duplicates by **label plus title**, so a week of failure is one issue
  with seven comments rather than seven issues, and **closes with a comment on the first
  green run** — the half that makes a label mean anything.
- `ops_log.py`: the weekly row on the unprotected `ops-log` branch, which doubles as the
  keep-alive commit. **Idempotent per date**, so a re-run of the scheduled job does not
  double-count the week, and a failed usage read renders `—` rather than `0` — an absent
  number must not look like a quiet week.
- `tokens-due`: was referenced by `docs/09` §4's `health.yml` step and **had never been
  implemented**. Reads dates only; exits 0 with a count and lets the caller apply the
  threshold, because the threshold belongs to the check rather than to the plumbing.
- `usage`'s summary keys renamed to `r2_class_b_mtd` to match what that same step reads.
  A windowed run (`--days N`) gets `_window` instead of claiming to be month-to-date: a
  threshold compared against the wrong window is the kind of wrong that looks right.

### Added — `release archive`, which cannot be exercised until M5.5

- `infra/release.py` assembles the restore archive from the bytes **production served**,
  verifying every member against the manifest before it goes in — an archive of
  regenerated bytes would only prove the generators still run. Parts split at 1.5 GB with
  a `parts.txt` of SHA-256s, and member metadata is fixed so the same fixtures make the
  same archive.
- **Nothing is published, so `fetch` has never been called against a real object.** The
  tests drive it against a fake. **A green suite here is not end-to-end verification**;
  the first real run is the M5.5 restore drill, after M5.1 puts bytes in R2.

### Added — `loremfile purge` and `loremfile verify-live` (M4.3)

- `infra/purge.py` and `loremfile purge --site|--url`: site prefixes and format pages in
  batches of 100 (the Free-plan maximum). **Fixtures are never purged by `--site`** —
  their bytes never change, so a purge could only discard a still-correct entry and cost
  an R2 read to refetch identical bytes. `--url` is the takedown path and names the URL
  explicitly, so no routine deploy can purge a fixture by accident.
- `infra/verify_live.py` and `loremfile verify-live --mode smoke|daily|full`: the header,
  length, type and hash contract against production, needing no credentials.
- **The 429 retry lives here and must never reach the probe.** `verify-live` retries our
  own rate limit after 10 s (docs/12 §4); `probe` treats the *absence* of a 429 as its
  failure. Separate modules with separate fetchers — a shared one with a flag would be
  one wrong argument from a probe that cannot see what it exists to see. A test asserts
  both halves at once.
- The CSP check is asymmetric on purpose: markup **must** carry the sandbox policy and a
  PDF or video **must not**, because an unexpected CSP breaks viewers and passes every
  other check.
- `--inject-failure` reports a path as failing without it being so (REQ-27): the issue
  automation is a control, and a control nobody has seen fire is one nobody can trust.
- `docs/19` §3 and #22: the Class B measurement is **corroborated from the billing side**
  — the owner reads R2 → Overview's Class B month-to-date counter immediately before and
  after the run, because it is not reachable from an API token. Two agreeing consumption
  records, or a disagreement that is a finding in its own right. If they agree, RISK-22's
  residual is **accepted-on-evidence**, where *evidence* means two agreeing consumption
  records and **not an observed invoice**.

### Added — `loremfile usage`, and the Class B measurement pre-registered (M4.3)

- `infra/usage.py` and `loremfile usage [--days N]`: R2 operations from the GraphQL
  Analytics API, split into Class A and Class B, with the query shape verified against
  the live API before being written against.
- **Attribution is by dimension, not by a total.** `r2OperationsAdaptiveGroups` reports
  `actionType: GetObject` with `actionStatus: userError` — a GET for a key that does not
  exist — so a delta in *that* counter is 404s and nothing else. A 24-hour read already
  shows **1,329** of them, which are this project's own probe bursts.
- **The measurement is pre-registered in `docs/19` §3 and on #22**, and the 404 result
  re-scoped it: with 404s confirmed cached, repeating one path would measure the *cache*
  rather than the billing, so it fires **1,000 unique paths**. Thresholds, the quiet
  window and the baseline-stability requirement are fixed before the run; an unstable
  baseline is a **precondition failure, not a verdict**.
- **One distinction the metric cannot collapse**, stated in `docs/19` §3: this records
  what R2 counts as an **operation**. Whether Cloudflare **bills** a recorded `userError`
  GetObject is pricing policy applied to that record, and no API reports it.

### Verified — 404s are cached after all; the rate limit's real limit is its counting key

M2.4 probe runs 7-9, against thresholds **pre-registered before the runs**.

- **404s are cached.** A non-zero `Age` on the **first** sample of all three runs — branch
  (a), 3/3 positive with `K ≤ 2`. `docs/03` §3's **original** 3-minute claim was closer to
  right than the correction that replaced it; that correction rested on `MISS/MISS`
  readings of `cf-cache-status`, which cannot establish it. Caching is verified; the
  **duration** is not — 3 minutes is Cloudflare's documented default for 404/410, not a
  measurement.
- **ADR-026's premise flips, and its conclusion is unchanged.** A status-code TTL would
  now replace a *working* 3-minute default with Free's 2-hour floor — **less** justified
  than adding one where nothing existed, and still carrying the G3 purge dependency.
- **The rate limit enforces consistently when the load reaches one counter**: runs 6 and 9
  both fired at request **294**, at 262 and 252 req/s from a single data centre. Runs 4-5's
  apparent intermittency was not approximate counting — the identity sampling showed one
  runner's traffic spread across **3, then 6** data centres. The rule counts per
  `(ip.src, cf.colo.id)`, so **a client distributed across N data centres gets roughly N
  times the budget**. That is the property to plan against.
- **RISK-22: both controls exist and are evidenced.** `docs/19` §3's scenarios are
  unchanged — they already assume every request is an R2 read.

**Verified list, corrected.** Now verified on evidence: ADR-013 (query-string cache key,
`Age`-based), 404 caching, rate-limit enforcement at a single identity. Still **not**
verified: the 404 cache **duration**, rate-limit behaviour across a split identity, and
whether R2 bills a 404 as a Class B read (needs `loremfile usage`, M4.3).

### Verified — ADR-013 at the edge; and the rate limit is *not* reliably enforcing

M2.4 probe run 5, 13 checks, 1 failed.

- **ADR-013 is verified.** `?x=2 served with Age 15s from the entry ?x=1 populated` — one
  observation is proof, since a non-zero `Age` can only come from an entry an earlier
  request populated, and that request carried a different query string. It took changing
  the instrument to get there: `cf-cache-status` passed on run 3 and failed on run 4
  unchanged, because edge nodes within a colo do not share a local cache.
- **`404-caching-absent` passes**, so the inverted check reports the accepted state.
- **The rate limit did not enforce this run, and that revises run 4's verdict.** Run 4
  blocked at request 547 at 156 req/s; run 5 was unblocked at 69 req/s (cached) and
  45 req/s (unique paths), both above the 30 req/s threshold — and the slower run had
  **more** headroom after crossing it (4.3 s against 1.9 s), so window coverage does not
  explain it. `docs/08` §5.5 and RISK-22 now say deployment is verified and **consistency
  is not**. It matters more than it would have: with 404 caching confirmed absent, this is
  the only bound, and an intermittent bound is closer to no bound.
- The probe's two unmeasured variables are now measured: load is sustained for a fixed
  **duration** rather than a fixed count, and the `ip`/`colo` the edge attributes the run
  to is sampled from `/cdn-cgi/trace` on our own zone — the counter is per
  `(ip.src, cf.colo.id)`, so a split identity is a **precondition failure**, not a verdict.

### Changed — status-code TTL for 404s rejected (ADR-026); the check inverted

- **ADR-026**: a status-code edge TTL was considered and **rejected**. What was verified
  first: `edge_ttl.status_code_ttl` is in the rulesets `PUT` schema and is not
  plan-gated, but **Free's minimum edge TTL is 2 hours**. Declined because it helps
  neither scenario in `docs/19` §3 (both use unique paths), the repeat-404 case it does
  help is not in the threat model and is already capped by the rate limit, and it would
  make **G3 depend on a purge call** where today it depends on nothing. Reopens only on a
  `cost` issue showing real repeat-404 abuse.
- `docs/03` §3 now **states** that 404s are not cached, with the measurement, instead of
  calling the 3-minute claim "in doubt". RISK-22's residual risk is **accepted, not
  mitigated**.
- The probe's `404-caching` check is **inverted**: it asserts 404s stay uncached and
  fires if that changes. A check that fails forever on a known, accepted property is
  noise, and noise is how a real finding gets scrolled past.
- `AGENTS.md` gains a fourth shape — **promoting a detail string** — with instances from
  both the operator and the author reading the same output in the same week. It has no
  automated defence; the only guard is a check that cannot report what it did not assert.

### Fixed — M2.4 probe results, and two things I recorded as verified that were not

- **Rate limit: verified working** (run 4). The rule is deployed, valid and enforcing,
  and it **counts cache hits** — 429 at request 547 of a 600-request burst against a
  single cached object. `cf.colo.id` survives as written and does **not** join the
  falsified list. Recorded in `docs/08` §5.5 with the read-back as evidence.
- **Enforcement is not instantaneous.** Run 3 completed 600 requests at 156 req/s with no
  429; run 4 was blocked ~5 s in. The rule bounds **sustained** abuse, not short bursts —
  now stated in `docs/08` §5.5 and `docs/19` §3.
- **404 caching: confirmed absent.** `edge_ttl.mode: respect_origin` with no
  `Cache-Control` from R2 on a 404 leaves nothing to respect. `docs/03` §3's 3-minute
  claim was wrong.
- **`query-string-cache-key` was recorded as verified twice and was not.** The assertion
  was right; the *instrument* was unreliable — it passed on run 3 and failed on run 4
  unchanged, because edge nodes within a colo do not share a local cache, so a MISS says
  only that this node had not seen it. It now measures `Age`, where a non-zero value on
  `?x=2` is positive evidence. **ADR-013 is marked configured-but-unproven** until that
  reports, and it should not be called verified again before then.
- **RISK-22 updated, not closed**: one control works, the other never existed.
  `docs/19` §3's headline numbers are unchanged — scenario 1 already assumed every request
  is a read — but the rate limit is now the *only* bound.

### Added — the uploader's plan and its two gates (M4.3, first part)

- `infra/upload.py`: `plan_fixtures`, `plan_removals`, `plan_site` as **pure functions**,
  so every rule is testable without a bucket, plus `tests/unit/test_upload_plan.py`.
- **There is no overwrite action.** A live object whose hash differs from the manifest
  fails the job: at that point either the manifest or the bucket is wrong and guessing
  which is how a published byte changes. Asserted on the enum, so one cannot be added
  by accident.
- **Gate: no upload to an unlocked prefix.** M3's lock deferral stops here, which is what
  keeps it from outliving its reason (`docs/08` §2). A disabled rule does not count as
  coverage.
- **Gate: never rebuild an `expected_drift` path.** The deploy fails when the
  carry-forward artifact is missing rather than regenerating — a rebuild produces
  different bytes on other hardware. All five missing paths are named in one run.
- `docs/09` §7: **a digest bump is never merged as routine automation.** Bumps batch into
  one deliberate PR at the M3 → M4 boundary that also runs `build --all --audit`. The
  automated PR carries **no checks at all** — GitHub does not run workflows on pull
  requests opened with `GITHUB_TOKEN` — so it is a notification that a new image exists,
  not a change ready to land.
- `AGENTS.md`: the three shapes of an assertion that is not assertable — *passes on
  absence*, *cannot fire*, *asserts something else* — each with its detection question and
  the instance that produced it.

### Fixed — four probe checks that could not fail for the reason they named

Found by running the probe against production and then auditing all twelve checks
against two questions: *if the thing it names were broken, would this fail?* and *could
this fail for a reason other than the thing it names?*

- **`404-caching` reported `cf-cache-status` and passed on `DYNAMIC`** — which means the
  edge caches no 404s at all and every unique missing path is an R2 read, contradicting
  `docs/19` §3's cost model. Now asserts a cacheable status *and* a HIT.
- **`cors-warm-cache` named the cache in its title and never asserted it**, so it would
  have passed on a response that was never cached, proving half of what it claimed.
- **`www-redirect` followed the redirect** — `urlopen` does by default — and asserted
  against the apex root, which correctly 404s while no site is uploaded. A working
  redirect looked broken. `fetch` now returns redirects instead of following them.
- **`url-normalization` compared two CSPs without requiring either to exist.** With no
  header rule at all both sides are `""` and the comparison passes. Found by the audit,
  not by a run.
- **`rate-limit` concluded "the rule is not in effect" from load it never generated.** A
  sequential burst reaches 12–20 req/s and cannot cross a 30 req/s threshold. The burst is
  now concurrent, the achieved rate is measured, and falling short is a **precondition
  failure** — never a verdict. The rule is also read back from the zone separately, so a
  missing rule is a finding rather than an inference from silence.
- `settle()`: a **bounded** poll (180 s) that keeps "never appeared within N" and
  "appeared and was wrong" as different findings. `docs/11` §7.2b records that apply must
  be followed by a settle window.

### Added — `loremfile probe`, M2.4

- Ten edge checks and two bucket checks, plus `--up` / `--down`, and an `infra.yml`
  `probe` mode that cleans up with `if: always()`.
- **No check may pass vacuously.** Each states its preconditions, and an unmet
  precondition is a **failure** — never a skip and never a pass. A parametrised sweep
  drives every edge check against a 404 and asserts it fails for that reason, so a check
  added later is covered without anyone remembering to write a test for it.
- The probe raises explicitly rather than using `assert`: `python -O` strips assertions,
  which would turn the entire probe green while testing nothing.
- `probe.fetch` has **no retry logic at all**, rather than a flag that could be set
  wrongly: `verify-live` treats a 429 from our own rate limit as retry-after-10s, and
  the probe treats its absence as failure. An AST test fails if a loop or a sleep appears
  in it — checked on the tree, not the text, because the first version grepped the source
  and tripped on the docstring explaining the rule.
- `_locktest/` is a real result now that M2.3 applied the 53 rules: creation succeeds,
  overwrite and delete are both refused, and the original byte is still there afterwards.

### Fixed — the toolchain digest now lives in exactly one place

- `propose-digest-bump` had never been able to run: the digest bump rewrote
  `.github/workflows/*.yml` with `sed`, and `GITHUB_TOKEN` may not update workflow files
  (`refusing to allow a GitHub App to create or update workflow .github/workflows/ci.yml
  without workflows permission`). The duplication was invisible until the automation that
  depended on it actually ran.
- `tools/TOOLCHAIN_DIGEST` is now read by a `setup` job in each workflow and consumed as
  `container.image: ${{ needs.setup.outputs.digest }}`. No `workflows: write`, and the
  `sed` is gone. **Verified before adopting**: a throwaway workflow confirmed
  `container.image` accepts `needs.*.outputs.*` on GitHub-hosted runners and that the
  runner pulls and creates the container from it.
- Guard: `tests/unit/test_workflows_pinned.py` fails if any workflow names a toolchain
  image literally — on a `container.image` line or anywhere else — and if a job uses the
  `setup` output without depending on `setup`, since that expression resolves to an empty
  string and GitHub then runs the job on the bare runner instead of failing.

### Added — infrastructure as desired state, M2.1 and M2.2

- `infra/zone-settings.json`, `bot-management.json`, `rulesets/*.json` (6 phases),
  `dns.json`, `r2-cors.json`, `r2-cors.wrangler.json`, `r2-locks.json` (53 rules,
  generated by `loremfile infra locks --write`). Every file was generated **from
  `docs/08`'s own JSON blocks**, and `tests/unit/test_infra_files.py` re-parses the
  document and compares, so the two cannot drift.
- `infra/cloudflare_api.py` (auth, retry with backoff, pagination), `infra/apply.py`
  (the eight steps of `docs/08` §6), `loremfile infra apply [--dry-run]`, and
  `infra.yml` modes `apply-dry-run` and `apply`.
- **Zone scoping is a hard precondition, not a convention.** Ruleset entry points are
  written with a full PUT and this account holds two unrelated production zones, so a
  request aimed at the wrong zone id would *replace* their rules. `Client` refuses every
  write until `verify_zone()` has read the zone and confirmed its name is `loremfile.dev`;
  each write then re-checks its own target path, which catches a mis-templated URL after
  a correct verification. `ZoneScopeError` is deliberately a separate exception so no
  `except CloudflareError` can degrade it into a warning, and `--dry-run` prints the
  resolved zone id and hostname before anything could write.
- A refused permission is reported as `manual` with its dashboard path rather than
  failing the run — the `[VERIFY]` permission names in `docs/08` §6 are unconfirmed until
  M2.3.

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

### Fixed — the carry-forward bytes were not being retained at all (M3.6)

- `docs/09` §3.1's `new-fixtures` artifact (the bytes) was replaced in M3.1 by a 4 KB
  `fixture-inventory` of hashes, for quota reasons. That was fine until `expected_drift`
  existed: for those five paths the manifest describes bytes that could not be rebuilt
  **and were not stored anywhere**. New `carry-forward-fixtures` artifact holds exactly
  those paths — about 69 MB — with **90-day retention**. Retention is a correctness
  setting here, not a convenience; `fixture-inventory` goes to 90 days too, so the
  CPU-to-bytes correlation outlives the question.
- `ci.yml` logs each runner's CPU model and SIMD flags, so "hardware or encoder?" is
  answered from artifacts rather than argued.
- **RISK-21 reworded to the reading the evidence actually supports**: CPU-dependence on
  a heterogeneous pool, *not* nondeterminism. Two GitHub-hosted runs are two VMs, and
  the second attempt reproduced a hash generated days earlier — luck under
  nondeterminism, expected under CPU-dependence. The distinction decides whether
  reproducibility is recoverable at all: homogeneous hardware would recover it.
- `expected_drift` matching is now **exact paths, never prefixes**. The set is five and
  enumerable; a prefix match was broader than the evidence and invited marking `opus/`
  wholesale later.
- ffmpeg's `-cpuflags 0` recorded in `docs/06` §4 as a **negative** finding with the
  reason, so it is not retried in a year.
- `docs/15`: **M2, then M4.3 and M4.4, now precede the remaining M3 format groups.**

### Added — the determinism audit, and an accepted RISK-21 (M3.6)

- `loremfile build --audit` (`docs/06` §8) reports drift against the manifest in **two
  sections**. A fixture whose catalog entry sets the new `expected_drift` field is known
  not to reproduce off the CI reference fleet and is listed separately without failing
  the run; anything else is real drift and does. Without the split, four media fixtures
  would appear in every audit, and an issue that reports expected behaviour every month
  is one nobody reads.
- `expected_drift` on five paths: `mp4/1080p-10s.mp4`, `mp4/10mb.mp4`, `mp4/50mb.mp4`,
  `opus/30s.opus`, `webm/720p-5s-vp9.webm`. `manifest check` reports a mismatch on
  these and does not fail — measured: two attempts of the **same commit on the same
  runner label** produced different bytes for the Opus and VP9 fixtures, so this is
  run-to-run variation, not a stable per-fleet reference. Every other path stays fatal. A typed field rather than a marker inside `notes`, because the
  audit classifies on it and prose that has to be parsed goes wrong the first time
  someone rewords it.
- Workflows pin `runs-on: ubuntu-24.04`. It does not fix the CPU dispatch, but it removes
  one axis of drift for free — `ubuntu-latest` moving underneath would be a silent change
  of reference.
- `docs/06` §4 now states that **the reference is the toolchain digest *and* the runner
  label**; `tools/TOOLCHAIN_DIGEST` alone reads as though it were the whole reference.
- `docs/06` §11 and `docs/11` §7.9 document the media authoring loop: **two round trips,
  by design** — push, read the entries CI printed, `manifest adopt`, push. A failing local
  `manifest check` on a media path is expected, not a broken checkout.
- RISK-21 accepted, with the recovery path made explicit: **red deploy → supersede at a
  new path, never regenerate and overwrite.** Immutability is held by the manifest lock
  and the R2 bucket locks, neither of which regenerates anything; reproducibility is a
  convenience for audits and the *fallback* restore path, so the exposure is a compound
  failure of fleet drift and lost archives, for media only.
- Checked and rejected: ffmpeg's global `-cpuflags 0` is byte-identical on both the Opus
  and the VP9 paths, so it constrains libav* internal SIMD without reaching an external
  encoder's own dispatch.

### Added — `manifest check` verifies the regenerated bytes; `manifest adopt` (M3.6)

- `loremfile manifest check` now performs the regenerated-byte comparison `docs/06` §7
  always specified and deferred to M3, and prints the exact entries to commit when the
  bytes disagree — what `docs/11` §5 promised. `ci.yml` runs it **before** the
  integration tests and copies the output into the job summary.
- `loremfile manifest adopt --from <file>` takes those entries without hand-editing
  `manifest.json`. It **refuses any path already published on the base branch**, so
  "take CI's answer" can never rewrite frozen bytes.

### Fixed — the pinned image is not sufficient on its own for media

- `libx264`, `libvpx` and `libopus` each choose SIMD kernels from the CPU features they
  find at runtime, and no ffmpeg option reaches that choice — `-cpuflags 0` and
  `-cpuflags sse2` produce byte-identical output, so this is the encoders' own dispatch.
  Four of 36 media fixtures hash differently on GitHub's runners than on the author's
  machine. **CI is the authority**, because CI builds the bytes the deploy uploads.
  Recorded in `docs/06` §4, `docs/11` §5, `AGENTS.md` and as **RISK-21**.

### Added — video, audio and HLS (M3.6)

- `mp4/` (9), `webm/`, `mkv/`, `mov/`, `avi/`, `ogv/`, `ts/` (1 each), `hls/` (6),
  `mp3/` (7), `wav/` (2), `flac/`, `ogg/`, `opus/`, `m4a/`, `aac/`, `aiff/` (1 each) —
  36 launch fixtures. All synthetic: ffmpeg's `testsrc2` pattern and a 440 Hz tone, so
  no third-party footage or recording is redistributed.
- `generators/media_video.py`, `generators/media_audio.py`, `generators/hls.py`,
  `validators/media.py` (ffprobe, plus the structural checks ffprobe cannot make).
- `wav/10mb.wav` is **exactly** 10,000,000 bytes — an `exact` size class, not `approx`.
- `docs/06` §4 gains an ffmpeg row and marks mutagen verified.

### Fixed — three recipes that were wrong before they were run

- **docs/06 §4's mutagen row named a proving fixture with no tags on it**
  (`mp3/sine-440hz-3s.mp3`). The tagged fixture is `mp3/with-id3v2-tags-3s.mp3`. The
  cross-check test could not have caught this: it verifies that a proving fixture is
  parametrised, not that it exercises the claim.
- **docs/05 §6's MP4 bitrate formula** discounted the analytic bitrate by 0.97 for muxer
  overhead. Measured, the overhead is far smaller: the discount put `1mb.mp4` 4.85 %
  under target — inside the 5 % tolerance, but one encoder change from failing the
  build. Undiscounted, the three sized MP4s land at −2.09 %, +0.63 % and +0.17 %.
- **HLS segments came out 8 seconds long, not 2.** The segmenter can only cut on a
  keyframe and libx264's default GOP is 250 frames, so a 10-second source produced two
  segments where the catalog declares five. Keyframes are now forced at every segment
  boundary with scene-cut detection off.

### Added — office documents and e-books (M3.5)

- `docx/` (5), `xlsx/` (6), `pptx/` (3), `rtf/` (1), `epub/` (1) — 16 launch fixtures.
- `generators/office.py`, `validators/office.py`. The validators read every OOXML
  package a second time as a plain zip, because python-docx and openpyxl both read back
  their own conventions and will reopen a package Word would refuse.
- `xlsx/with-formulas.xlsx` carries **cached results** for every formula. openpyxl has no
  API for them and writes an empty `<v/>`, which reads back as `None` in pandas — a
  formula fixture without them parses perfectly and is useless.

### Fixed — openpyxl was never reproducible on its own

- `docs/06` §4 credited python-docx, openpyxl and python-pptx with deterministic *part
  names*. The M3.5 spike showed the claim was aimed at the wrong thing: openpyxl spools
  each worksheet to a temporary file and adds it with `ZipFile.write`, so that entry is
  stamped from the filesystem, which no clock patch can reach. Raw output changed on six
  of eight consecutive runs. `util.zipnorm` is what makes xlsx stable. The row is now
  three rows, one per library, each with its own proving fixture.
- The RTF validator counted `\par` as a substring, so `\pard` — which opens every
  paragraph — was counted twice. `rtf` also moved out of the shared text validator list
  into `validators/office.py`, keeping its text props and gaining a brace-balance check:
  an unbalanced RTF opens as an empty document in some readers and garbage in others,
  and neither reports an error.

### Added — PDF (M3.4)

- `pdf/` — 12 launch fixtures: A4 and Letter, portrait and landscape, with images,
  with a table, encrypted, blank, a hand-written minimal file, and two sized.
- `generators/pdf.py`, `validators/pdf.py` (pypdf plus `qpdf --check`).

### Changed — determinism claims are now checkable

- `docs/06` §4's prose list of library determinism claims became a table with a proving
  fixture and a verification date per row. `tests/unit/test_determinism.py` parses it and
  fails if a verified claim has no run-twice test, if a test claims a row the table does
  not have, or if a row still marked unverified has been quietly parametrised.
- `AGENTS.md`: spike determinism before writing a catalog entry.
- `docs/06` §13: validators assert structure, not parseability.

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
