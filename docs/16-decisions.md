# 16 — Architecture Decision Records

Format: context → decision → consequences. Status is *Accepted* unless noted.

## ADR-001 Static objects on R2 behind Cloudflare, no server, no Worker in the hot path
- **Context**: goals G4–G6 (near-zero cost, ≤ 1 h/week maintenance, attack resistance) with a no-ops owner.
- **Decision**: all runtime behaviour = R2 objects + Cloudflare declarative rules. No compute in the request path in Phase 1.
- **Consequences**: no custom 404, no query-driven behaviour, directory index needs a rewrite rule; in exchange there is nothing to patch, no request cap, and cost stays in free tiers. Dynamic features go to specific Worker routes later (ADR-003).

## ADR-002 Apex domain serves fixtures; site lives in the same bucket
- **Context**: `loremfile.dev/pdf/x.pdf` is the product; a subdomain for files would be worse UX. R2 custom domains can be attached at the apex (confirmed by community reports; it replaces root A/AAAA records). R2 has no directory index.
- **Decision**: attach the apex to the bucket; upload site HTML as objects (extensionless keys + `index.html`); one URL-rewrite rule for `/` and trailing slashes; `www` redirects to apex.
- **Consequences**: one deploy path, one cache, one set of rules. Pages product unused. Site pages exist under two keys. Local preview differs slightly from production (no rewrite).

## ADR-003 Dynamic endpoints only on Worker routes, only after Phase 1, on Workers Paid
- **Context**: Workers Free caps at 100k requests/day and would put code in front of every file.
- **Decision**: reserve `/random/*`, `/bytes/*`, optional `/dl/*` for a Worker with explicit routes; pay USD 5/month when built.
- **Consequences**: static traffic never hits the Worker; the Worker can be removed without affecting fixtures.

## ADR-004 No AWS, no Vercel
- **Context**: both were offered. S3/CloudFront bill egress; Vercel is another platform; each is another account to secure.
- **Decision**: Cloudflare only. AWS S3 may be used as an optional off-account cold backup (Q-05); Vercel not used.
- **Consequences**: single vendor dependency mitigated by GitHub Release archives and regenerable fixtures (ADR-007).

## ADR-005 Immutability: never change bytes at a published path
- **Context**: tests hash fixtures; tutorials embed URLs for years; the incumbents' unreliability is the reason this project exists.
- **Decision**: published paths are frozen; fixes are new paths with `supersededBy`; only legal takedowns remove objects, leaving a manifest tombstone; CI enforces via the manifest lock and the storage layer enforces via R2 bucket locks (ADR-023).
- **Consequences**: some mistakes live forever (documented, deprecated); naming discipline matters; storage grows monotonically (bounded by budget checks). **Immutability attaches on publication to R2, not on entry into `manifest.json` (amended M3.6, `03` §7.1).** What this ADR protects is embedded URLs and hashed fixtures in other people's tests; both require the bytes to have been served. A manifest entry whose bytes never reached the bucket has no consumer, and is removed rather than tombstoned — a tombstone asserts prior publication.

## ADR-006 Format landing pages stored twice (`pdf` and `pdf/index.html`)
- **Context**: R2 serves keys literally; `/pdf` and `/pdf/` must both work without a Worker; Free plan rules cannot use regex.
- **Decision**: uploader writes both keys; a `concat()`-based rewrite handles the slash form; canonical URL is `/pdf`.
- **Consequences**: trivial extra storage; a unit test ensures both copies are identical.

## ADR-007 Binaries are not in git; the manifest is the lock; GitHub Releases archive bytes
- **Context**: ~1 GB of fixtures; git/LFS unsuitable; reproducibility across toolchain drift is imperfect.
- **Decision**: `manifest.json` (hashes) is committed; fixtures are regenerated only when new; published bytes are archived as release assets (delta tarballs + periodic snapshots).
- **Consequences**: the repo stays small; restore needs Releases + generators; the determinism audit is advisory.

## ADR-008 Cloudflare configuration as idempotent desired-state JSON + scripts (not Terraform)
- **Context**: one zone, ~10 rules, a no-ops owner; Terraform adds state storage and provider churn.
- **Decision**: `infra/*.json` + `apply.py`/`audit.py` using full-`PUT` semantics on phase entry points and `PATCH` on settings.
- **Consequences**: no state file; drift is detected weekly; Terraform remains a drop-in alternative if a future maintainer prefers it.
- **Exception (ADR-030, 2026-09-15)**: `http_request_firewall_custom` is shared with incident rules, so it is written one rule at a time and never `PUT`.

## ADR-009 Reproducible generation in a digest-pinned container with hash-pinned dependencies
- **Context**: fixtures must be regenerable for audits and restores; supply-chain risk.
- **Decision**: single toolchain image; `SOURCE_DATE_EPOCH`; determinism guards; zip normalisation; single-threaded encoders.
- **Consequences**: slower builds (parallelism across files instead); upgrades are deliberate PRs.

## ADR-010 Fixtures are byte-exact over the wire (`no-transform`); site is compressible
- **Context**: clients compare `Content-Length` to manifest bytes and hash bodies; Cloudflare compresses text types by default.
- **Decision**: `Cache-Control: … no-transform` on fixtures only.
- **Consequences**: text fixtures transfer uncompressed (egress is free); site HTML stays small via brotli.

## ADR-011 Security headers by response-header rules; `sandbox` CSP only on markup fixtures
- **Context**: HTML/SVG fixtures could be abused as an XSS/phishing host; some PDF viewers break under sandbox.
- **Decision**: three header rules (files, markup, pages) keyed on path suffixes, plus an optional fourth keyed on the response `Content-Type`; markup gets `sandbox; default-src 'none'` with an explicit allow-list for the fixture's own images, media, inline styles and fonts (`03` §4.2), so it stays inert but renders; PDFs/media get no CSP because browsers' built-in PDF viewers have failed under restrictive CSPs (Chromium 40328564, Mozilla 1582115). The suffix rules depend on URL normalization staying on, which is therefore desired state.
- **Consequences**: the three header rules plus the two URL rewrites use 5 of the 10 free transform rules; `/pdf/` (rewritten to index.html) is treated as a page.

## ADR-012 Hotlinking, bots and agents are welcome; all challenge features off
- **Context**: the product is programmatic access; challenges break curl/agents; AI crawlers are an audience.
- **Decision**: Browser Integrity Check, Bot Fight Mode, Block AI Bots, managed robots.txt, hotlink protection all off; `security_level` essentially off; WAF Free managed rules on; one generous rate limit with verified bots exempt.
- **Consequences**: abuse mitigation is cost-bounded rather than prevented; the runbook has escalation steps.

## ADR-013 Query strings are ignored by the cache key and never used
- **Context**: an earlier draft believed the Free plan could not exclude the query string from the cache key; Cloudflare's Cache Rules availability table shows "Ignore query string" on all plans (only per-parameter lists, headers and cookies are Enterprise-only).
- **Decision**: the cache rule sets `cache_key.custom_key.query_string.exclude = "*"`; the origin ignores query strings; no behaviour is ever keyed on them (a `?download` variant, if built, is a path — `/dl/…`).
- **Consequences**: `?v=123` cache-busting is harmless and free; the remaining read-amplification vectors are unique 404 paths and per-origin cache entries (`19` §3).
- **Status: verified at the edge, M2.4 probe run 5 (2026-09-09).** `?x=2 served with Age 15s from the entry ?x=1 populated`. One such observation is proof: a non-zero `Age` can only come from an entry an earlier request populated, and that request carried a different query string. Getting there took changing the instrument — `cf-cache-status` passed on run 3 and failed on run 4 with nothing changed in between, because edge nodes within a colo do not share a local cache, so a MISS says only that *this* node had not seen it. It was recorded as verified twice on that evidence before the `Age` measurement replaced it.

## ADR-014 No hostile fixtures on the main domain
- **Context**: EICAR/zip bombs/JS PDFs are useful but trip Safe Browsing/AV and mail filters, which would break every user.
- **Decision**: forbidden on loremfile.dev (policy §5); revisit on a separate domain in Phase 4.
- **Consequences**: some security-tool testers are not served in v1.

## ADR-015 Decimal and binary size units both exist, spelled differently
- **Context**: "10 MB limit" means 10,000,000 or 10,485,760 depending on the stack; boundary tests need exact ±1 files.
- **Decision**: `mb` = decimal, `mib` = binary; `-plus-1`/`-minus-1` boundary variants; validators enforce exactness classes.
- **Consequences**: more files, clearer tests, a naming page explaining it.

## ADR-016 Raw fixtures `noindex`; pages indexable; AI crawlers allowed
- **Context**: search should land on pages with context; agents should still find fixtures via `llms.txt`/manifest.
- **Decision**: `X-Robots-Tag: noindex` on files via header rule; `robots.txt` allows everything.
- **Amended 2026-09-15 — the legal pages that name a person are the exception** (ADR-028). `/legal/imprint` and `/legal/privacy` carry `X-Robots-Tag: noindex, nofollow, nosnippet` (header rule `legal_pages_noindex`, `08` §5.3) and the same `<meta name="robots">`; `robots.txt` still allows everything for `User-agent: *` — Google honours `noindex` only on a page it is not blocked from crawling — but disallows both paths for a named group of AI tokens, each checked against its vendor's own documentation (`04` §6); both pages are excluded from `sitemap.xml`, `llms.txt`, `llms-full.txt`, `search-index.json` and all JSON-LD. Every other page stays indexable and every AI crawler stays welcome everywhere else.

## ADR-017 No analytics script; usage from Cloudflare zone analytics
- **Context**: privacy, CSP strictness, no cookie banner.
- **Decision**: no JS analytics; weekly numbers copied into `ops-log.md`.
- **Consequences**: no consent banner is needed because nothing is stored on the visitor's device and no tracking happens — not because no personal data is processed. Cloudflare processes IP addresses and request metadata as our processor, so the controller obligations in `13` §3/§3a still apply.

## ADR-018 Loremfile Sans is a generated font, not a third-party font
- **Context**: redistributing third-party fonts as CC0 fixtures is impossible; a font fixture is still needed.
- **Decision**: generate a box-glyph ASCII font with fontTools; DejaVu is used only as a tool to rasterise labels in images.

## ADR-019 Ed25519-only certificates in v1
- **Context**: RSA/ECDSA key generation and ECDSA signing are non-deterministic; storing a private key is forbidden.
- **Decision**: derive an Ed25519 key from a public fixed seed at build time; never write the key; certificates are deterministic.
- **Consequences**: RSA cert fixtures wait for a deterministic approach (Phase 2 research).

## ADR-020 Domain registered at Cloudflare Registrar (not split from DNS/CDN)
- **Context**: splitting registrar and DNS reduces blast radius of one account compromise, but adds an account and a payment method to keep alive for a no-ops owner; Cloudflare Registrar is at cost with one-click DNSSEC and a transfer lock.
- **Decision**: Cloudflare Registrar; compensate with hardware-key 2FA and the transfer lock. Revisit if the owner prefers separation (Q-06).
- **Consequences**: the disaster-recovery promise is honest about it — content and a mirror hostname within a day; `loremfile.dev` itself only as fast as Cloudflare restores the account (RISK-19); the repository README is the out-of-band pointer to the current host.

## ADR-021 Manifest entries are committed by the PR author; CI regenerates and verifies; deploy never rewrites the manifest
- **Context**: the first draft left it ambiguous who produces manifest entries and had deploy re-running `manifest update`, which would always dirty `generated_at` and fail the diff; it also generated nothing on `main` because the entries were already committed.
- **Decision**: the author runs `loremfile manifest update` in the toolchain container and commits the entries with the catalog change. CI (`build --new`) regenerates everything absent from the merge-base manifest and `manifest check` verifies the committed hashes/props. Deploy (`build --missing-in-bucket`) regenerates only objects missing from R2, verifies against the committed manifest, and uploads. `generated_at`/`toolchain_image` are excluded from the lock comparison.
- **Consequences**: the manifest diff in a PR is reviewable; CI cost is proportional to what changed; deploy is idempotent and can be re-run at any time to backfill missing objects.

## ADR-022 Maintenance operations run through GitHub workflows, never with local credentials
- **Context**: infra apply, behavioural probes, restores and takedowns need T1/T2, but the security model keeps tokens in GitHub only.
- **Decision**: `infra.yml` (modes `audit`, `apply`, `probe`, `restore`, `redact`) and `deploy.yml` (`--apply-removals`) are the only places tokens are used. Takedowns are ordinary PRs that tombstone the entry; deletion happens in deploy. Probe objects live under `_probe/` and the only delete paths in the code are tombstoned keys and that prefix.
- **Consequences**: an engineer or agent needs only GitHub access to operate the service; `wrangler login` is used once by the owner in M0.

## ADR-023 R2 bucket locks on every fixture prefix
- **Context**: without them, immutability rested on code paths and on T2 not leaking; R2 offers prefix-scoped, indefinite lock rules that refuse overwrites and deletes at the storage layer.
- **Decision**: one indefinite lock rule per `{format}/` prefix, applied by the owner with an admin token (`infra/r2-locks.json`); site keys and `_probe/` stay outside the locks. Takedowns lift one rule temporarily.
- **Consequences**: a leaked T2 can add fixtures and rewrite site pages (caught by the daily integrity check) but cannot alter or remove published fixtures; new formats need an owner step; the lock-rule count limit is verified in M0.4 (RISK-20).

## ADR-024 Launch with an explicit 228-fixture set; the rest of phase 1 follows in batches
- **Context**: the full phase-1 catalog is ≈ 416 files, and building ~50 generator/validator pairs to that breadth before launch would take a quarter at the offered cadence.
- **Decision**: `05` §9 lists the launch set (P1, 228 files, ≈ 515 MB); the remaining 188 phase-1 rows are P1b (M7). Every format family is represented at launch so the URL scheme, headers and site are complete from day one.
- **Consequences**: earlier launch and feedback; some search-demand fixtures arrive later; the immutability rules apply from the first deploy.

## ADR-025 Cost control is an automated analytics read, not a billing alert
- **Context**: Cloudflare's usage-based billing notifications require a Pro plan or a pay-as-you-go account; this zone is Free.
- **Decision**: `health.yml` reads R2 operations and zone traffic daily through the GraphQL Analytics API with a read-only token (T4) and opens a `cost` issue above 5 M reads month-to-date; the same step writes the weekly ops-log line, which doubles as the keep-alive commit for scheduled workflows.
- **Consequences**: detection latency ≤ 1 day; one more token to rotate (yearly); the owner still reviews billing monthly; the ops-log lives on an unprotected `ops-log` branch so the `main` ruleset needs no bypass for any workflow.

## ADR-026 Status-code edge TTL for 404s — considered and rejected (M2.4)
- **Context (premise corrected 2026-09-09)**: this ADR was written on the belief that 404s are **not** cached. **They are** — verified in M2.4 probe runs 7-9 with a non-zero `Age` on the first sample of every run; `respect_origin` falls back to Cloudflare's default caching behaviour, which is 3 minutes for 404/410. The earlier reading came from `cf-cache-status`, which cannot establish it. **The corrected premise is not a reason to revisit this decision — it strengthens it.** A status-code TTL would replace a working 3-minute default with a 2-hour floor (Free's minimum), which is *less* justified than adding one where nothing existed, and it would still carry the G3 purge dependency below.
- **What was verified before deciding**: `edge_ttl.status_code_ttl` is in the rulesets `PUT` schema (`status_code` or `status_code_range` plus `value` in seconds) and is **not plan-gated**. But **Free's minimum Edge Cache TTL is 2 hours**, so 3 minutes is unreachable and any adoption starts at a 2-hour floor.
- **Decision**: **rejected.** Do not add a status-code TTL.
  - **It helps neither scenario in `19` §3.** Both use *unique* paths, so each request is a distinct cache key and a longer TTL on any one of them changes nothing.
  - **The case it does help — repeated requests to one missing path — is not in the threat model**, and the rate limit already caps it at 30 requests/second per IP per data centre (verified, `08` §5.5).
  - **It would put a contract on a purge call.** G3 ("never break a published URL") today depends on nothing: a path that 404s and later becomes a fixture is served correctly the moment it is uploaded. With a 2-hour cached 404 it would be served stale until purged, so G3 would depend on the deploy's purge succeeding — and `09` §6 does not purge fixture URLs at all. That is a real cost paid for speculative hardening.
- **Consequences**: `19` §3's numbers stand as written (scenario 1 already assumed every request is a read). *(Corrected 2026-09-10: this line previously read "404s stay uncached", which the premise correction above had already falsified. Two sentences in one ADR disagreeing is worse than either being wrong on its own.)* With 404 caching confirmed, the bound on repeat-404 volume is the cache *and* the rate limit rather than the rate limit alone — which is a further reason this ADR's decision needs no revisiting. The probe asserts the caching behaviour rather than failing on it, so a change would surface as a finding.
- **What would reopen this**: a `cost` issue showing **real repeat-404 abuse** — many requests to the same missing path, not many unique ones. That is the only shape a status-code TTL would help, and it is currently hypothetical.

## ADR-027 `tls_1_3` holds `zrt`, not `on` — the desired state contradicted itself (M4.4)

- **Context**: `tls_1_3` was the only one of 23 zone settings that did not converge after M2.3. The zone reports `zrt`; `infra/zone-settings.json` asked for `on`, and `loremfile infra apply` reported `updated` on every run — drift that `audit.yml` would raise weekly, forever.
- **What the two values actually are**: Cloudflare's `tls_1_3` setting takes `"on"`, `"zrt"` or `"off"`, where **`zrt` is TLS 1.3 *with* Zero Round Trip Time Resumption (0-RTT)**. It is not a different protocol version; it is the same TLS 1.3 plus 0-RTT. The separate `0rtt` setting is the same knob from the other side.
- **The contradiction**: the desired state declared **both** `"tls_1_3": "on"` **and** `"0rtt": "on"`. Those cannot both hold. With 0-RTT enabled the zone reports `zrt`, so the file asked for a configuration and then wrote one half of it in a form that denies the other half. The zone was never wrong; the desired state was internally inconsistent.
- **Evidence that the write never landed**: `modified_on` is `null` for both `tls_1_3` and `0rtt`, while every setting M2.3 genuinely changed carries a timestamp (`ssl`, `always_use_https`, `automatic_https_rewrites`, all `2026-09-09T13:49Z`). So `apply` reported `updated` for a write that moved nothing — the same "report the write, not the state" failure that `infra audit` has to avoid (`09` §3.4), showing up in a second place.
- **Decision**: the desired state holds **`"tls_1_3": "zrt"`**. This changes **no zone behaviour whatsoever** — it writes the configuration that was already declared and already in force, in the vocabulary the API uses to report it.
- **Rejected alternative — set `0rtt: "off"` so that `tls_1_3` reads `on`.** That would also converge, and it was rejected for two reasons. It contradicts the desired state's own `0rtt: "on"`, which was a deliberate declaration, so "fixing" the inconsistency by discarding the other half is a coin toss dressed as a decision. And the exposure 0-RTT carries — replay of early data — is **inert on this origin**: every response is a public, immutable GET, so a replayed request produces a byte-identical response and changes nothing. Nothing here has a session, a cookie, a credential or a side effect.
- **Consequences**: 23 of 23 settings converge, so any `infra-drift` issue about zone settings after this is a real one. `zrt` also keeps the round-trip saving on resumed connections, which is worth having for a hotlink CDN where clients open many short-lived connections.
- **What would reopen this**: **a non-idempotent endpoint.** Phase 3's Worker routes (`/random`, `/bytes/N`, `/dl/`) are still side-effect-free GETs and do not. Anything that accepts a POST, mutates state, or acts on a credential does, and 0-RTT should be turned off before it ships rather than after.

## ADR-028 Impressum under § 18 Abs. 1 MStV, not § 5 DDG; its values exist only as production secrets (M4.1)

*This records the owner's decision and the facts it rests on. It is not legal advice, and the regulator's position below is the owner's cited basis rather than something this repository verified.*

- **Context**: `/legal/imprint` and `/legal/privacy` must identify the operator. Which law sets the requirement decides what the page has to contain, and the identity of a private individual must never enter a public repository, its issues, pull requests, logs or artifacts.
- **Facts the decision depends on** — every one of them is a reopen trigger if it stops being true:
  1. loremfile.dev has **never been offered for payment**.
  2. It carries **no advertising**.
  3. It has **no sponsorship** and **no affiliate links**.
  4. The Berlin regulator (mabb) treats an unpaid service as *geschäftsmäßig* only when regular advertising covers its costs.
- **Decision**:
  - loremfile.dev is **not geschäftsmäßig under § 5 DDG**. The Impressum follows **§ 18 Abs. 1 MStV**: **name**, **a serviceable address**, and the contact address **hello@loremfile.dev**. **No telephone number.**
  - The values exist **only** as the GitHub `production` environment secrets **`IMPRINT_NAME`**, **`IMPRINT_STREET`** and **`IMPRINT_POSTAL_CITY`** — three separate plain secrets, **never a JSON blob**, because GitHub warns that structured data "can cause secret redaction within logs to fail".
  - Committed templates hold `%%IMPRINT_*%%` placeholders only. Rendering, and every guard around it, is specified in `13` §3b and lands with M4.1.
- **Reopen triggers**: **any** payment, advertising, sponsorship or affiliate link. Any one of them makes § 5 DDG apply, and **a second contact channel must be added before that change ships** — not after. `14`'s "Ideas explicitly rejected" no longer allows a "sponsored by" line, and Q-12's "no sponsor or donate link" is tied to this ADR.
- **Consequences**: Q-07 and Q-21 are resolved without recording any value (`18`). `AGENTS.md` rule 5 forbids writing the values anywhere, for any reason. The pages are kept out of search and AI crawlers as far as the web's conventions allow (ADR-016 amendment), and `13` §3b states the limit plainly: those measures reduce reading, they cannot prevent it.

## ADR-029 One concurrency group for every job that reads or writes the zone (2026-09-15)

- **Context — #58 was a race, not drift.** Audit run `34905539807` read `http_response_headers_transform` at 22:44:46 and saw three rules; deploy run `34905529591` applied the fourth at 22:45:16–21. The audit compared a committed file with four rules against a zone mid-apply and opened "Infra drift detected". A later audit closed it through `gh_issue`. `deploy.yml` had `concurrency: deploy`; `infra.yml` and `audit.yml` had none — so an audit could read mid-apply, and an `infra.yml` apply could race a deploy's apply, both writing whole ruleset phases.
- **Decision**: one group, **`loremfile-zone`**, with **`cancel-in-progress: false`**, on `deploy.yml` (workflow level), `infra.yml` (workflow level) and **`audit.yml`'s `infra` job** (job level). **Outside it**: `audit.yml`'s `determinism` job, which touches nothing remote; and **`health.yml`**, which is read-only — and a cancelled pending health run would silence alerting. `tests/unit/test_zone_concurrency.py` pins all of this.
- **[VERIFY] `queue`, and the result.** GitHub's documentation: "By default, any existing `pending` job or workflow in the same concurrency group will be canceled and the new queued job or workflow will take its place", and a `queue` property (`single` by default; `max` allows up to 100 pending) changes that. **actionlint 1.7.12** — the latest release, checksum-verified — **rejects the key** at both levels: `unexpected key "queue" for "concurrency" section`. It is therefore **not used**.
- **Leftover risk, stated rather than assumed away.** At most one run can be *pending* in the group; a third arrival cancels it. A pending deploy replaced by a newer deploy is benign **for fixtures**: the newer run builds `--missing-in-bucket`, so whatever the replaced run would have published is still missing and is published then — and an `expected_drift` path whose bytes the newer run's artifact does not carry fails its upload gate rather than being rebuilt. **It was not benign for `infra/`**: `infra_changed` diffed `HEAD~1..HEAD`, so an `infra/` change in the replaced run's commit was never applied when the newer commit did not touch `infra/` itself (the next two bullets). A pending `infra.yml` apply that is replaced is visible to whoever dispatched it. **A pending scheduled audit that is replaced opens no issue** — the passes-on-absence shape. `11` §7.2 tells the operator to confirm the Monday audit *completed*, and to dispatch it if it shows *cancelled*.
- **Follow-up, 2026-09-15 — the infra base is the last successful push deploy.** `deploy.yml`'s `infra_changed` step runs `loremfile infra changed` (`src/loremfile/infra/changed.py`), which diffs `infra/` against the `head_sha` of the most recent `deploy.yml` run with `event: push` on `main` and `conclusion: success`, excluding the current run. A cancelled or failed run is no evidence that its commit reached the zone, and a `workflow_dispatch` may have been a dry run or a staged `only:` deploy. **No such run → `changed=true`. A lookup that fails → the step fails**, with the reason; so does a base missing from the checkout or not an ancestor of the commit being deployed (a re-run of an older deploy). None of these is read as either answer. Every run in the list must carry the fields the selection reads, so a renamed API field fails the step instead of making every run look unqualified — which would read as "no such run", and apply. `tests/unit/test_infra_changed.py` pins each case, including a replayed history in which `HEAD~1` finds nothing and the new base finds the replaced run's change.
- **Rejected: applying on every deploy.** It would remove the lookup, and compare-before-write makes it cheap in API calls. It is rejected because an apply converges every committed setting, and one of them is an emergency lever: `11` §7.4 step 4 is Under Attack Mode, which is `security_level = "under_attack"`, while `infra/zone-settings.json` commits `"essentially_off"`. Applying on every merge would switch Under Attack Mode off mid-incident on the next unrelated merge — a fixture, a typo fix. Applying only when `infra/` changed confines that to merges that change `infra/` (or that follow a failed deploy of one), and §7.4 tells the operator not to make them, or dispatch an apply, while it is on.
- **What would reopen this**: actionlint accepting `queue` (or the key otherwise verified to validate and behave as documented) — then add `queue: max` to all three and delete the §7.2 instruction.

## ADR-030 WAF custom rules are written rule by rule — an exception to ADR-008 (2026-09-15)

- **Context**: ADR-008 writes each ruleset phase with a full `PUT` of its entry point, which is safe only in a phase nothing else writes.
  - `http_request_firewall_custom` is the phase the runbook uses during an incident: `11` §7.4 adds custom rules in the dashboard. Cloudflare on a `PUT` of an entry point: "This API method requires that you include in the request all rules you want to keep in the ruleset, or else they will be removed." Under ADR-008 the next apply after an incident would delete the incident's rule.
  - ADR-028 wants one rule here: refuse self-identifying AI agents on `/legal/imprint` and `/legal/privacy`. robots.txt only asks, and OpenAI says of `ChatGPT-User` that "robots.txt rules may not apply".
- **Decision**:
  - **A rule is ours when its `ref` starts with `loremfile_`.** Every committed rule carries the prefix.
  - **Per-rule endpoints, compare first.**
    - `infra apply` adds with `POST …/rulesets/{ruleset_id}/rules`, changes with `PATCH …/rules/{rule_id}` (the whole rule), and removes a rule of ours no longer committed with `DELETE …/rules/{rule_id}`.
    - Each write happens only when `apply.compare_rules` finds a difference.
    - With no entry point, `POST /zones/{id}/rulesets` creates one carrying our rules.
  - **Never `PUT` this phase.** `cloudflare_api.NEVER_PUT_PHASES` refuses the request before it is sent, dry run included.
  - **Any rule without the prefix is a `warning` and is never deleted**, in `apply` and in `infra audit`. The audit opens no drift issue for it.
  - **The writer stays serialised.** The writer is `infra apply`, which runs only in `deploy.yml` and `infra.yml`, both in the `loremfile-zone` group (ADR-029). `tests/unit/test_zone_concurrency.py` pins every `infra apply` invocation to that group.
  - **`contains` with the vendor's casing, not `lower()`.** Cloudflare: "All string operators are case-sensitive unless explicitly stated as case-insensitive". Each vendor documents its token's casing.
  - **The tokens** are the `04` §6 AI group minus `Google-Extended`, which "doesn't have a separate HTTP request user agent string". `OAI-AdsBot` is added to both, quoted from OpenAI: "OAI-AdsBot only visits pages submitted as ads, and the data collected by OAI-AdsBot is not used to train generative AI foundation models."
- **[VERIFY] `http.user_agent` on Free — resolved 2026-09-15: accepted.** Cloudflare's documentation neither restricted nor confirmed it, so the first write decided.
  - **The write:** push deploy run `34940201386` (`99334dd9e2`) reported `loremfile_legal_pages_ai_agents` `updated — added, creating the entry point`, with `failed=0`. T1's permission to write the phase is confirmed by that same write.
  - **The behaviour:** probe run `34941018789` passed `legal-pages-ai-agents` (7 tokens refused on 2 pages, a browser not).
  - **The path scope:** a hand check from colo TXL found `GPTBot` refused on both legal pages, but not on `/pdf/minimal.pdf` or `/robots.txt`.

  The evidence is in `08` §5.7. Still unverified: the Anthropic header strings (below).
- **Consequences**:
  - 1 of 5 custom rules is used.
  - Rule order in the phase is not managed.
  - An incident rule survives every apply, and shows as a warning until it is ported into `infra/` or removed.
  - The Anthropic tokens are matched without a vendor-published header string (`08` §5.7).
- **What would reopen this**: Cloudflare offering a whole-phase write that preserves rules it was not given; incident rules moving to a phase nothing else writes; or a vendor publishing header strings that do not contain its robots.txt token.

## ADR-031 Release assets stay mutable; release tags are protected by a ruleset (2026-09-15)

- **Context**: A takedown must also leave the release archives (`09` §10). GitHub on immutable releases: "Release assets cannot be modified or deleted"; the tag "cannot be deleted while the release exists"; "If you delete the immutable release, you can delete the tag, but you cannot reuse the same tag name."
- **Decision**: immutable releases stay **off**. `release redact` rebuilds affected parts in place and refuses an immutable release, naming the cost: deleting the whole release, losing the restore archive for every other fixture in it, and burning the tag name. It reads `GET /repos/{owner}/{repo}/immutable-releases` first and fails if the setting is on.
- **Integrity instead**: manifest hashes in git and `parts.txt`; a tag ruleset on `refs/tags/v*` blocks deletion and updates.
- **Reopen if**: GitHub allows replacing a single asset of an immutable release.
