# 18 — Open Questions for the Owner

Each question lists the default assumed by this documentation. If the owner says nothing, the default stands. Answers are recorded here and in `16-decisions.md` when they change a decision.

| ID | Question | Default assumed | Why it matters |
|---|---|---|---|
| Q-01 | Confirm the domain name: `loremfile.dev` (available; two small GitHub CLIs share the word "loremfile", no hosted service, no trademark found) vs `fixtures.dev` (available; sports-schedule search noise) | `loremfile.dev` | Brand, SEO, all docs |
| Q-02 | Buy defensive aliases (`fixtures.dev`, `loremfile.com`, `loremfile.org` were available on 2026-09-06)? | No (≈ USD 9–13/year each if yes; redirect to apex) | Cost vs copycat risk |
| Q-03 | GitHub location: personal account `<OWNER>/loremfile` or a new org `loremfile/loremfile`? | Personal account | Org adds admin overhead but eases hand-over; can be transferred later |
| Q-04 | R2 bucket location hint: `auto`, or pin to a region near most expected users (`ENAM`/`WEUR`/`APAC`)? | `auto` | Cache misses' latency only; immaterial with tiered cache |
| Q-05 | Off-account cold backup to AWS S3 (Glacier Deep Archive ≈ USD 0.001/GB-month; ≈ USD 0.01/month) in addition to GitHub Releases? | No (GitHub Releases suffice); yes if the owner wants to use the AWS account for something | Resilience vs another account to keep alive |
| Q-06 | Registrar: Cloudflare Registrar (default) or a separate registrar (e.g. Porkbun, ≈ USD 13/year) to split domain control from CDN/DNS? A separate registrar turns "recover the domain from a lost Cloudflare account" from a support process into a DNS change | Cloudflare Registrar, with the honest RTO in `11` §7.6 | Blast radius vs simplicity (ADR-020, RISK-19); the reviewer recommends splitting |
| Q-07 | Contact addresses: `hello@`, `security@`, `dmarc@` forwarding to the owner's mailbox — which mailbox? | The owner's primary email | Email Routing setup; legal notices |
| Q-08 | Approve in principle a **separate** domain for unsafe fixtures in Phase 4 (EICAR, zip bombs…)? | Not now; revisit after month 6 | Legal/reputation exposure |
| Q-09 | Session cadence: is ~2 h/week for the first month and ~1 h/week afterwards acceptable? | Yes | Determines M3 elapsed time (≈ 4–6 weeks) |
| Q-10 | Launch posts: the owner will publish agent-drafted posts on HN, dev.to, Reddit, X/Bluesky under their own name? | Yes | RISK-01 |
| Q-11 | Budget: approve up to USD 5/month for Workers Paid when Phase 3 starts, and up to USD 15/year in domains? | Assume yes for Phase 3 only | ADR-003 |
| Q-12 | Should the site show a "sponsor / donate" link (e.g. GitHub Sponsors) to offset the domain cost? | No | Keeps the pitch clean |
| Q-13 | Preferred bucket name (`loremfile-public`) and toolchain image name (`loremfile-toolchain`)? | As stated | Cosmetic |
| Q-14 | When will M0 (account, domain, bucket, tokens) be done? | Unknown; M1 and M3 proceed with placeholders, M2 and M5 wait | Schedules the first deploy |
| Q-15 | May the agent post answers linking to loremfile.dev on Stack Overflow / forums under the owner's accounts, or only draft them? | Draft only | RISK-01 |
| Q-16 | Accept R2 bucket locks with the takedown ceremony (owner lifts one lock rule with an admin token, then re-adds it)? | Yes (ADR-023) | Immutability guarantee |
| Q-17 | Should HTML/SVG fixtures render their own images, styles and media when opened directly, while staying script-free? | Yes (ADR-011 CSP allow-list) | Usability of markup fixtures |
| Q-18 | On a legal takedown, re-publish GitHub Release assets without the object and remove the generator parameters? | Yes | Completeness of removals |
| Q-19 | Is the launch set in `05` §9 the right 229 fixtures, or should specific fixtures be swapped in or out? | As listed | Launch scope (ADR-024) |
| Q-20 | Is the account pay-as-you-go (payment method on file)? If yes, the Usage Based Billing notification may be available as a second cost signal | Assume not; the automated check is the control | Cost detection |
| Q-21 | Privacy notice: name the controller publicly (legal name and a postal address, which Art. 13 GDPR expects) or publish a contact address only and give the identity on request? | **No default** — the owner must answer | `13` §3/§3a cannot be rendered; blocks M4.2 |

**Q-07 and Q-21 have no working default.** Every other question here falls back to the documented default if the owner says nothing; these two cannot. `13` §3 is a published legal text — an unreachable contact address or a missing controller identity is a defect in itself — so it keeps the `<CONTACT_EMAIL>` and `<CONTROLLER>` placeholders and **M4.2 is blocked** until both are answered. They are listed as open blockers in the "Implementation status" issue every session.

## Questions a reviewer may ask, answered

- **Why not put the docs site on Cloudflare Pages?** Because the apex must serve files, and Pages cannot proxy R2 without Functions; a second hostname for files defeats the purpose (ADR-002).
- **What if R2 cannot be attached to the apex?** M0.4 discovers it before any content work. Fallback: attach `www.loremfile.dev` to the bucket instead and add a Single Redirect from the apex to `www` with the path preserved; fixture URLs then read `www.loremfile.dev/pdf/…`. Documented in RISK-11; not expected.
- **Why is there no `/latest` alias or versioned paths?** Objects are immutable; the path is the version. Aliases would create a mutable surface (ADR-005).
- **Why 100 MB max?** Bandwidth-amplification cap and comfortably under Cloudflare's 512 MB cacheable limit; speed-test sites exist for bigger files.
- **What happens on a read-amplification attack?** Query strings are ignored by the cache, so the vectors are unique 404 paths and many IPs; cost is bounded (rate limit → ≤ 30 rps per IP per colo; R2 Class B at USD 0.36/M); the daily usage check opens a `cost` issue above 5 M reads month-to-date; runbook §7.4.
- **How does an agent discover the right fixture?** `llms.txt` → `manifest.json` (descriptions, tags, props) or `/{format}/index.json`; Phase 3 adds an MCP server.
- **Who reviews PRs if the owner does nothing?** The engineer/agent in the weekly session; CI is the gate; CODEOWNERS names the owner for `LICENSE`, `docs/13-legal-and-policy.md` and `infra/` but is informational (not enforced) while there is a single maintainer.
- **What is the recovery time if Cloudflare disappears?** Content and a mirror hostname within one working day from Releases + generators; `loremfile.dev` itself only as fast as Cloudflare support restores the account, because the domain is registered there (runbook §7.6, RISK-19, Q-06).

## Answers to the implementer review (2026-09-07)

A fresh-context review by a "junior implementer" reader produced 28 questions. Each is answered here and the answer is now also in the referenced document.

| # | Question (abridged) | Answer | Where |
|---|---|---|---|
| 1 | What does `build` generate on a PR vs on `main`, and where does deploy get bytes for keys missing in R2? | PR: `build --new` = catalog paths absent from the merge-base manifest; deploy: `build --missing-in-bucket` regenerates exactly the missing keys, verified against the committed manifest | `06` §5, `09` §3.1–3.2, ADR-021 |
| 2 | How do `generated_at`/`toolchain_image` survive `git diff --exit-code`? | Deploy never runs `manifest update`; those two fields are excluded from the lock and only change in PRs | `06` §7 |
| 3 | How do I get T1/T2 for M2.3/M2.4 and delete probe objects? | You don't: `infra.yml` modes `apply` and `probe` run in GitHub; `probe --down` deletes `_probe/*` | `09` §3.2b, `15` M2.3–M2.4, ADR-022 |
| 4 | Which fixture does each truncation use? | Listed per edge fixture as `depends_on` | `05` §3.13 |
| 5 | Sized fixtures: content, parameters, miss handling? | §6 recipes with the `fit` algorithm; a miss fails the build | `05` §6 |
| 6 | Dataset seed, word lists, prefix property, `bio` charset? | Seeds `loremfile:dataset:*`, word lists in `data/wordlists/`, prefix property holds, `bio` is Latin-1-safe | `05` §2 |
| 7 | Multilingual corpora? | Generated pseudo-text per script from character inventories; no third-party text | `05` §7 |
| 8 | Are `props` frozen? | Yes; `description`, `tags`, `notes`, deprecation fields are not | `06` §7, `09` §7 |
| 9 | When is `build-and-validate` required and what are the check names? | Job names; `lint-and-test` from M1.5, `build-and-validate` from M3.1 | `09` §1 |
| 10 | Variable scope? | Repository variables; secrets in the `production` environment | `09` §1–2 |
| 11 | First release snapshot? previous tag? | `v1.0.0` is a full snapshot; `git describe --tags --abbrev=0 <tag>^` | `09` §3.5 |
| 12 | Third-party libraries and the determinism guard? | Guards patch (not raise) `os.urandom`, `random`, clocks, `uuid4`; per-library notes given | `06` §4 |
| 13 | Certificate details? | Fixed serial, subject, validity 2020–2120, Ed25519 from a public seed | `06` §4 |
| 14 | Default charset and overrides? | `utf-8` appended by the loader; the full override list | `05` §1 rule 7 |
| 15 | Rename `rss-2.0-feed.xml`? | Yes → `rss2-feed.xml` | `05` §3.7 |
| 16 | `bin/` seed: name or path? | Full path, the standard `ctx.seed` | `05` §3.10 |
| 17 | Who writes site copy; is AI-drafted text acceptable? | Agent drafts in `site/content/`; acceptable; facts cross-checked by a test | `07` §5 |
| 18 | Sources for docs/legal pages? | Table with every page's source; licence text added | `07` §1, `13` §1.1 |
| 19 | Popular list, related formats, families? | Fixed lists and catalog fields | `05` §8, `06` §3 |
| 20 | Which fixture per format for smoke/daily headers? | Smallest P1 fixture by bytes, ties by path | `09` §3.3, `12` §4 |
| 21 | How is REQ-27 tested? | `health.yml` `inject_failure` input / `verify-live --inject-failure` | `01`, `06` §10, `12` §5 |
| 22 | Where do Lighthouse, actionlint, gitleaks run? | On the host; informational except gitleaks | `06` §9 |
| 23 | Real `<OWNER>` and mailbox? | Placeholders until Q-03/Q-07; M1/M3 do not need them | `15` header |
| 24 | When is M0 done? | Q-14; M2/M5 wait, M1/M3 do not | `18` |
| 25 | `control-characters.txt` edge case? | Yes, `edge_case: true` | `05` §3.6 |
| 26 | `float16` in the Arrow types fixture? | No; the type list is now explicit | `05` §3.7 |
| 27 | Is any delete allowed? | Only tombstoned keys (`--apply-removals`) and `_probe/*` | `09` §5 |
| 28 | Audit and unreadable settings? | Warning, exit 0 unless `--strict` | `08` §6 |

## Answers to the principal-engineer review (2026-09-07)

| # | Question (abridged) | Answer | Where |
|---|---|---|---|
| 1 | Source for "Free cannot ignore the query string"? | A misreading of the Cache Rules settings page (only per-parameter lists are Enterprise). Corrected: the cache rule ignores query strings | ADR-013, `08` §5.4, `03` §6 |
| 2 | Pay-as-you-go and billing alerts? | Unknown (Q-20); the control is the automated analytics read either way | ADR-025, `19` §2 |
| 3 | T2 deletes; accept bucket locks? | Yes: locks on every fixture prefix; takedown lifts one rule with the admin token | ADR-023, `08` §7b, `11` §7.8 |
| 4 | Should markup fixtures render? | Yes; CSP keeps `sandbox` and allows the fixture's own images/styles/media | `03` §4.2, ADR-011 |
| 5 | Who holds tokens locally; read-only token for the agent? | Nobody holds write tokens locally; T4 (read-only analytics) exists for `health.yml`; the agent operates through workflows | `08` §2 10b, ADR-022 |
| 6 | Hit-ratio target scope; Tiered Cache required? | Aggregate zone-wide; Smart Tiered Cache is required desired state | REQ-22, `08` §5.4 |
| 7 | AI-crawler settings after 2026-09-15? | `ai_bots_protection: disabled`, `cf_robots_variant: off`, `content_bots_protection: disabled` | `08` §4 |
| 8 | Takedown: release assets and generator code? | Assets redacted (`release redact`); generator params removed, code removed only if it embodies the content | `09` §10, `11` §7.8, `13` §7 |
| 9 | P1 = 417 deliberate? | No: launch set = the 229 files in `05` §9 (every family represented), the other 188 phase-1 rows are P1b | ADR-024, `15` M3/M7 |
| 10 | Permission group names? | Owner pastes them from `GET /user/tokens/permission_groups` during M0.4 | `08` §2 step 7 |
| 11 | CODEOWNERS vs 0 approvals? | Informational until a second maintainer exists | `09` §1, `02` §6 |
| 12 | 60-day scheduled-workflow rule? | Monday ops-log commit from `health.yml` is the keep-alive; re-enable procedure documented | REQ-27, `11` §5, RISK-10 |
| 13 | Reserve a fallback hostname now? | Not by default (Q-02); the README is the out-of-band pointer | `11` §7.6, RISK-19 |
