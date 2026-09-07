# Review log

Specification v1.0 was reviewed on 2026-09-07 by two independent, fresh-context reviewers before delivery. Their unedited reports are kept in `review/`:

- `reviewer-a-implementer.md` — read as a junior engineer told to implement end to end without asking anyone: 85 findings (3 blockers, ~30 major), 28 questions.
- `reviewer-b-principal.md` — principal engineer / security review that checked 46 vendor claims against live documentation (37 verified, 6 wrong, 3 unverifiable) and reviewed design, security, operations and consistency: 9 majors, ~30 minors, 13 questions.

Every finding was either fixed in the documents or explicitly answered; the answers to all 41 questions are recorded in `../docs/18-open-questions.md`. The most consequential corrections:

| Area | What was wrong | What changed |
|---|---|---|
| Build/deploy flow | The build never defined what to generate on a PR vs on `main`, and deploy rewrote the manifest it then diffed | `build --new` on PRs, `build --missing-in-bucket` on deploy, manifest committed by the PR author and verified by CI (ADR-021) |
| Credentials | Two milestones needed tokens on a laptop; probe objects could not be deleted | `infra.yml` workflow with `audit`/`apply`/`probe`/`restore`/`redact` modes; tokens never leave GitHub (ADR-022) |
| Cache key | Claimed the Free plan cannot ignore query strings — false | Cache rule excludes the query string; ADR-013 rewritten; cost model recomputed |
| Cost control | Relied on a billing notification the Free plan does not have | Daily automated R2-operations read with a read-only token; `cost` issue above 5 M reads (ADR-025) |
| Immutability | Enforced only in code paths | R2 bucket-lock rules on every fixture prefix (ADR-023); takedown ceremony documented |
| Markup fixtures' CSP | `default-src 'none'` would have blocked the fixtures' own images and styles | `sandbox` kept, explicit allow-list for the fixture's own resources |
| Toolchain | Image lacked `git`/`gh` though every job runs inside it; apt packages unpinned | Added and pinned; smoke test in `toolchain.yml` |
| Scheduled workflows | GitHub disables them after 60 days without repository activity | Weekly ops-log commit from `health.yml` as keep-alive; re-enable procedure |
| Scope | 417 phase-1 fixtures in a 30-hour estimate | Explicit 229-fixture launch set (`05` §9), 188-fixture P1b batches after launch (ADR-024); ≈ 73 h to launch, ≈ 110 h total |
| Disaster recovery | "One day on a new account" ignored that the domain lives in that account | Honest RTO; README as out-of-band pointer; RISK-19; Q-06 recommendation |
| Dozens of consistency items | Counts, rule tallies, test paths, milestone references, flag names, MIME/charset details, naming-grammar violation (`rss-2.0-feed.xml`) | Fixed; single sources of truth named |

A third fresh-context pass (`verification.md`) then checked closure of every finding and found 30 follow-ups introduced by the fixes (a leftover paragraph, a launch-set count, lock-rule consequences in three procedures, an invalid JSON example); all were fixed. Facts that still carry a **[VERIFY]** tag are collected in `../docs/08-infrastructure.md` §6 and resolved during milestones M0.4 and M2.3; none of them changes the architecture.

## Fourth round — external feedback (2026-09-08)

The owner forwarded a further review. Its findings, with disposition:

| Item | Verdict | Change |
|---|---|---|
| B1 site-integrity baseline stored in the bucket the check protects | **Correct, genuine flaw** introduced while fixing an earlier finding | Baseline is now a deterministic rebuild of the deployed commit from the repository (`07` §4, `09` §3.3); no manifest of site hashes is stored in the bucket |
| B2 03 said CORS is applied by `apply.py`; 08 says owner via wrangler; CI tokens cannot do it | **Correct** (stale sentence from the first draft) | `03` §5 now points at the owner step |
| M1 rate-limit `characteristics` includes `cf.colo.id` while the text says "IP" | **Half right**: the JSON is correct — Cloudflare documents `cf.colo.id` as mandatory in every rule on every plan — but the prose contradicted it | Explained in `08` §5.5 and `02` §8 |
| M2 heartbeat commit to `main` needs a ruleset bypass that would apply to every workflow | **Correct** | Heartbeat commits to an unprotected `ops-log` branch; no bypass anywhere |
| M3 policy forbids real names, dataset combines real names | **Correct as a wording conflict** | Policy reworded to "identifying a real person"; dataset states the coincidence explicitly |
| Md1 no `favicon.ico` → a 404 read per page view | **Correct** | `favicon.ico` and `apple-touch-icon.png` are site keys |
| Md2 Q-19 still said ~150 | **Correct** (the earlier sweep deliberately excluded document 18) | Fixed |
| Md3 operator precedence in `site_pages_headers` | **Not a bug** (`not` binds first) but explicit grouping is better | Parentheses added, precedence documented |
| Md4 tautological path test in the rate-limit rule | **Correct** | Explained in the rule description |
| Md5 restore accepts any URL | **Correct** (bounded by hash checks, but unnecessary exposure) | Restricted to the repository's release assets |
| Md6 "a 404 is a Class B read" unverified | **Correct** — R2's FAQ exempts only 401s | Marked as an assumption to measure in M2.4 |
| Nits (encrypted-fixture fallback, daily-mode time budget vs workflow timeout, `www` redirect before normalization) | **Correct** | Added |

Why the earlier rounds missed these: B1, M2 and Md5 are properties of mechanisms that were *added* in the fix passes, and the verification pass checked that findings were closed rather than re-reviewing the new mechanisms; B2 and M3 are cross-document consistency items outside the grep patterns the sweeps used; Md2 was excluded by a deliberate grep filter.
