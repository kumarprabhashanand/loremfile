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
- **Consequences**: 404s stay uncached and `19` §3's numbers stand as written (scenario 1 already assumed every request is a read). The **rate limit is the only bound** on request volume, so its enforcement latency — sustained abuse, not short bursts — is the property that matters. The probe asserts the uncached behaviour rather than failing on it, so a change would surface as a finding.
- **What would reopen this**: a `cost` issue showing **real repeat-404 abuse** — many requests to the same missing path, not many unique ones. That is the only shape a status-code TTL would help, and it is currently hypothetical.
