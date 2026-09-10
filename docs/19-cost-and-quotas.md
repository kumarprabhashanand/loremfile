# 19 — Cost, Quotas and What Money Would Buy

## 1. Baseline cost (the design as specified)

| Item | Cost | Source (verified 2026-09-06/07) |
|---|---|---|
| Domain `loremfile.dev` | ≈ USD 9–13/year (Porkbun list: USD 8.75 first year, 12.87 renewal; Cloudflare Registrar charges registry cost without markup) | Porkbun pricing API; Cloudflare Registrar docs |
| Cloudflare zone (Free plan): DNS, DNSSEC, CDN, WAF Free Managed Ruleset, 1 rate-limit rule, 10 transform rules, 10 cache rules, Single Redirects, Email Routing | USD 0 | Cloudflare plan docs |
| R2: ≤ 10 GB storage, ≤ 1 M Class A ops, ≤ 10 M Class B ops per month, egress free | USD 0 within tier; then USD 0.015/GB-month, 4.50/M Class A, 0.36/M Class B | R2 pricing page |
| GitHub: public repo, Actions on standard runners, Releases, GHCR public image | USD 0 | GitHub billing docs |
| **Total** | **≈ USD 1/month amortised** | |

## 2. Quotas and the guard rails that keep us inside them

| Quota | Free limit | Our guard | Expected use |
|---|---|---|---|
| R2 storage | 10 GB | CI fails above 8 GB total | ≈ 0.62 GB at launch, ≈ 1.06 GB after the P1b batches, then +0.5 GB/year |
| R2 Class A (writes) | 1 M/month | Deploys write only new keys and the site (~100 objects) | < 5,000/month |
| R2 Class B (reads) | 10 M/month | Edge cache + tiered cache; rate limit; automated daily usage check. The cache key includes the `Origin` header (query strings are excluded), so each distinct embedding origin costs one extra read per fixture per data centre | 0.1–1 M/month at 50k req/day and 95 % hit ratio |
| Cloudflare cacheable object size | 512 MB | Fixture cap 100 MB | max 100 MB |
| Transform rules | 10 | 5 used: 2 URL rewrites + 3 response-header rules, 6 with the optional response-type CSP rule (test asserts ≤ 10) | 5–6 (+2 for `/dl/` later) |
| Rate-limiting rules | 1 | 1 used | 1 |
| Cache rules | 10 | 1 used | 1 |
| Single Redirects | 10 | 1 used (+1 incident rule) | 1 |
| WAF custom rules | 5 | 0 used (incident use) | 0 |
| GitHub Actions minutes | unlimited on public repos (standard runners) | build budget 45 min; daily health ≈ 10 min | ≈ 400 min/month |
| GitHub Release asset | 2 GB per file | delta archives; snapshots ≈ 1 GB | fine |
| GHCR storage for public images | free | one image, few tags | fine |

Alerts: the Free plan has **no** usage-based billing notification (that is a Pro+/pay-as-you-go feature), so the cost control is the daily `health.yml` usage step (read-only analytics token) opening a `cost` issue above 5 M R2 reads month-to-date; plus HTTP DDoS alert (all plans), Registrar expiry mail, GitHub Dependabot alerts and the daily health issue.

## 3. Worst-case cost scenarios

> **Both controls verified in M2.4 (probe runs 7-9), and the numbers below are unchanged.**
> **404 caching exists**: a non-zero `Age` on the first sample of every run, so a repeated
> missing path is bounded. `respect_origin` falls back to Cloudflare's default caching
> behaviour, 3 minutes for 404/410 — the duration is documented rather than measured here.
> An earlier note in this section said 404s were not cached; that rested on
> `cf-cache-status`, which cannot establish it (`03` §3).
>
> **The rate limit enforces**, consistently when the load reaches one counter: runs 6 and
> 9 both blocked at request 294, at 262 and 252 req/s from a single data centre. **Its
> real limit is the counting key.** The rule counts per `(ip.src, cf.colo.id)`, and a
> single GitHub runner's traffic was spread across 3 and then 6 data centres — so a
> client distributed across N data centres gets roughly N times the budget before any
> counter fires. That is the property to plan against, not enforcement latency.
>
> The scenarios below already assume every request is an R2 read, so neither result moves
> them. What changed is that both controls are evidenced rather than assumed.

Conventions: R2 Class B reads at USD 0.36 per million after the 10 M free tier; the free tier is subtracted in every row; detection latency is the daily health/cost check (≤ 1 day) plus the weekly session to act (≤ 7 days). Query strings are excluded from the cache key, so `?random` busting costs nothing; the remaining read-amplification vectors are unique non-existent paths (each a 404 read cached 3 minutes), distinct `Origin` values (each a cache entry) and many IPs below DDoS thresholds. **Measured 2026-09-10, branch (a):** a GET for a missing key **is recorded by R2 as a Class B operation**, and Cloudflare's own free-tier consumption counter moves with those records. R2's pricing FAQ exempts only unauthorized (401) requests and says nothing about 404s; the model counts them, now on evidence rather than on conservatism. The measurement and its two deviations are below.

**The measurement, pre-registered before it was run.** The 404 result changed what it has to measure: with 404s confirmed cached (`03` §3), repeating one path would measure the *cache* rather than the billing. So it fires **1,000 unique paths**, each a guaranteed miss.

Attribution is by dimension rather than by a total. `r2OperationsAdaptiveGroups` reports `actionType: GetObject` with `actionStatus: userError` — a GET for a key that does not exist — so the delta in *that* counter is those requests and nothing else, rather than a total that other traffic also moves.

| Branch | Threshold | Meaning |
|---|---|---|
| **(a) they count** | delta ≥ 900 of 1,000 | Scenario 1's arithmetic holds. RISK-22's residual moves from accepted-on-assumption to **accepted-on-evidence**. |
| **(b) they do not** | delta ≤ 50 | Both cost scenarios shrink substantially and this section needs **recomputing downward** — a larger revision than it sounds, since the rows below are built on it. |
| **(c) ambiguous** | anything between, or a baseline that is still moving | **Precondition failure, not a verdict.** Re-run in a quiet window. |

Procedure: read the counter twice **10 minutes apart** and require the two to agree before starting (a moving baseline means other traffic is in flight); fire the 1,000; wait **10 minutes** for analytics to settle; read again, twice, and require *those* to agree. No deploy, probe or upload may run in the window.

**One distinction this cannot collapse.** The metric records what R2 counts as an **operation**. Whether Cloudflare **bills** a recorded `userError` GetObject is its pricing policy applied to that record, and no API reports it. The recorded operation is the best available proxy, and this section says so rather than eliding it.

**So the proxy is corroborated from the billing side, in the same window.** R2 → Overview shows the free-tier consumption counter for Class B operations month-to-date, which sits closer to the billing record than the analytics API does. **The owner reads it immediately before and immediately after the run** — the dashboard is not reachable from an API token, so this reading is part of the procedure rather than an optional cross-check.

- Both move by roughly 1,000 → the analytics dimension is corroborated by Cloudflare's own consumption accounting. **Two independent views of the same event**, which is materially stronger than one.
- They disagree → **a finding in its own right, and more interesting than either number**: one of the two is not counting what it appears to count, and the cost model is built on whichever is wrong.

If they agree, RISK-22's residual is recorded as **accepted-on-evidence** — and "evidence" means **two agreeing consumption records, not an observed invoice**. That distinction is written down because it will outlive everyone who remembers the difference.

| Scenario | Reads / cost | Stop condition |
|---|---|---|
| One IP requesting unique 404 paths at the rate-limit ceiling (30 rps) for 30 days | 77.8 M reads → 67.8 M billable ≈ USD 24 | `cost` issue on day 1–2; ASN/IP block in the weekly session → ≈ USD 5–6 |
| 1,000 IPs × 1 rps unique paths (below DDoS detection) for 7 days | 605 M reads ≈ USD 214 for the week; USD 930/month if never stopped | `cost` issue on day 1 (5 M crossed within 2 hours); custom rule blocking paths outside known prefixes or Under Attack mode; big red button within the week bounds it to ≈ USD 30–220 |
| Legitimate viral usage: 10 M requests/day, 97 % hit ratio | 9 M reads/month ≈ USD 0 | None needed |
| 500 distinct embedding origins × 400 P1 fixtures × ~30 data centres (worst-case fragmentation) | 6 M reads once, then cached ≈ USD 0 | None needed; Smart Tiered Cache keeps it lower |

### 3.1 The result, 2026-09-10 — branch (a), on both instruments

Attended run, handshaked with the owner: the dashboard readings are theirs, the analytics
readings are the token's.

| # | Reading | Time (UTC) | `GetObject`/`userError` MTD | Class B MTD | R2 → Overview |
|---|---|---|---|---|---|
| 1 | baseline | 09:04:40 | 1,865 | 2,028 | — |
| 2 | baseline | 09:15:22 | 1,866 | 2,036 | — |
| 3 | owner, before | ~09:16 | — | — | **1.89 k** |
| — | *burst: 1,000 unique paths, 0 blocked, 14.2 req/s* | 09:17:29–09:18:40 | | | |
| 4 | owner, after | ~12:20 | — | — | **3.3 k** |
| 5 | post-burst | 12:16:18 | 3,169 | 3,345 | — |
| 6 | post-burst | 12:26:44 | 3,169 | 3,351 | — |

**Attribution is exact rather than inferred.** The same counter restricted to the burst
window (09:15–09:25Z) reads **exactly 1,000**, and re-reads at 1,000 three hours later; the
zone side agrees within adaptive sampling (998 estimated 404s from one address). Every
request sent was recorded. Post-burst readings 5 and 6, ten minutes apart, agree on the
load-bearing counter **exactly** (3,169 both times); the Class B *total* differs by 6, which
is background `ListBuckets`/`HeadObject` traffic and not the dimension under test.

**The billing side agrees.** The owner's Overview moved **1.89 k → 3.3 k**; the analytics
Class B total moved **2,040 → 3,351** over the same span. Two independent consumption
records, agreeing on level and on movement. RISK-22's residual is therefore
**accepted-on-evidence**, in the sense defined immediately above: two agreeing consumption
records, not an observed invoice.

**Two deviations from the procedure, recorded rather than smoothed.**

- The baseline pair did **not** agree strictly — +1 on the load-bearing counter over 10m42s,
  about 0.1/min. That was reported before the burst was fired rather than after it. At that
  rate the drift cannot reach either branch boundary within the run — it would need roughly
  eight hours to move 50 — so it cannot change the verdict; but the criterion said *agree*
  and it did not, and the run continued on the owner's judgement rather than on the rule.
- The post-burst wait was **~3 hours**, not the 10 minutes specified, because the run was
  attended and the owner's second reading came late. This strengthens the result rather
  than weakening it: at that distance, "the dashboard has not caught up yet" is no longer
  an available explanation for a moving *or* a flat reading.

**An unsolicited replication, thirty minutes later.** At 09:48–09:49Z a single address
(`34.19.163.21`, a cloud host) sprayed the zone with `.env`, `phpinfo.php`,
`firebase-adminsdk.json` and similar credential paths — about 283 requests, 282 of them
cache misses, 43 distinct paths in the sample. R2 recorded **273** further
`GetObject`/`userError` operations in those two minutes. Nobody arranged it: the scenario
table's own vector arrived unprompted, on a domain with no audience yet, and produced the
same kind of record as the synthetic burst.

**What that observation calibrates.** The scan ran at **≈2.3 req/s** — 283 requests over
about 120 seconds, from **one** address, so it counted against **one**
`(ip.src, cf.colo.id)` counter. That is under a tenth of the rate limit's 30 rps threshold.
**The limit never engaged, and would not have**: nothing about a faster scanner is implied,
but the scanner that actually showed up was nowhere near the bound. Scenario 1 below models
a single IP sustaining the *ceiling* for thirty days. It is therefore an **upper bound**,
not an expectation, and that reading now rests on an observation rather than on an
assumption. The mitigation — a rule bounding requests to known prefixes — belongs to M4.4;
this section records only that the vector is live and that its observed rate is two orders
of magnitude below what the worst case assumes.

### 3.2 The pre-launch baseline, and why it is committed rather than queried

Before the site has an audience — no links, no index presence, nothing published — every
missing-key read is **uncontaminated background scanning**. That is the only period in
which the number can be measured cleanly, and once launch traffic arrives the pre- and
post-launch series are the comparison that says what launch actually cost. It cannot be
reconstructed afterwards, for a measured reason:

| Limit | Value | How it is known |
|---|---|---|
| Retention | **90 days** | the API's own refusal: *"cannot request data older than 12w6d"* |
| Maximum window per query | **32 days** | *"cannot request a time range wider than 4w4d"* |

Both were read off refusals on 2026-09-10 rather than off documentation, and both are
constants in `usage.py` (`RETENTION_DAYS`, `MAX_WINDOW_DAYS`) with a guard that refuses the
query before it is sent. Past 90 days the history is simply gone, so `health.yml` commits
the series to the `ops-log` branch — one row per **day**, backfilled by each weekly commit —
instead of leaving it to be re-queried. A month-to-date counter could not serve: it is
cumulative and resets at the month boundary, so it cannot express a rate.

**What the series holds so far.** The bucket's whole recorded history at the time of
writing, external traffic and ours separated:

| Day | Missing-key reads | Ours | External | Note |
|---|---|---|---|---|
| 2026-09-08 | 382 | 0 | **382** | the one clean full day: no probe run, no uploads, an empty bucket. The single `infra` dispatch that day was `verify-tokens`, 25 seconds of bucket metadata and no GETs |
| 2026-09-09 | 1,385 | ~608 | ~777 | M2.4 probe runs 3–9 from a GitHub runner |
| 2026-09-10 | 1,404 | 1,000 | ~404 | the Class B burst above |

The external figure is **≈380–780 missing-key reads per day**, and it is **bursty rather
than smooth**: one or two credential scans of 250–285 requests each account for most of it
(276 from a Chilean cloud host on the 8th; 271 and 257 from Canadian and Brazilian hosts on
the 9th; 283 on the 10th), with a long tail of scattered 404s from ~50 distinct addresses a
day. Between scans the rate falls to **≈0.1 missing-key reads per minute**; that is the
quiet floor, not the daily average, and quoting the floor as the baseline would understate
it by roughly a factor of three.

At 500/day that is ~15,000 a month, **0.15 % of the 10 M monthly free tier** — the cost is
not the point. The point is that the post-launch series will have something to be read
against, and that this is the last month in which the comparison can be established.

## 4. What spending a little money would buy — and whether it is worth it

Assessment requested by the owner. **The core design does not get significantly better with money**: the static R2 + CDN architecture is already the most robust and cheapest option at any budget, and the paid Cloudflare plans do not remove the constraints that matter here (custom cache-key headers/cookies, regex in rules and >512 MB caching are Enterprise features). Money buys optional capabilities and resilience at the edges:

| Option | Cost | What it buys | Verdict |
|---|---|---|---|
| **Cloudflare Workers Paid** | USD 5/month | Phase 3 endpoints (`/random`, exact-size `/bytes/N`, `/dl/` download variant, friendlier 404) with 10 M Worker requests/month included | **Worth it when Phase 3 starts**, not before. Keep the Worker off the static path. |
| **Off-account backup on AWS S3 Glacier Deep Archive** | ≈ USD 0.01–0.05/month for ~1–2 GB | An archive that survives a Cloudflare *and* GitHub account loss | Cheap insurance; recommended if the owner keeps the AWS account alive anyway (Q-05) |
| **Second domain for unsafe fixtures** (Phase 4) | USD 10–30/year | Serving EICAR/zip-bomb/exploit-shaped fixtures without endangering the main domain | Defer; decide at month 6 (Q-08) |
| **Defensive domains** (`fixtures.dev`, `loremfile.com`) | ≈ USD 9–13/year each | Copycat protection, vanity redirects | Optional; low value early |
| **Independent mirror** (Bunny Storage/CDN or Backblaze B2 + a second CDN) | ≈ USD 1–3/month | A live copy on another provider, strengthening the "never breaks" promise | Only if usage becomes significant (Phase 5) |
| **Cloudflare Pro** | USD 20–25/month | Full managed WAF + OWASP, 2 rate-limit rules, 25 transform rules, longer analytics, image polish (harmful here), usage-based billing notifications | **Not worth it**: the limits that matter here (regex in rules, custom cache-key headers, 512 MB caching) are still Enterprise-only; the one useful item, billing alerts, is replaced by the automated usage check |
| **Cloudflare Cache Reserve** | ≈ USD 0.015/GB-month + ops | Persistent cache layer that reduces R2 reads | Not needed: R2 reads are already free within 10 M and egress is free |
| **External uptime monitor with SMS** (UptimeRobot/Better Stack paid) | ≈ USD 7–10/month | Minute-level alerts to a phone | Not aligned with the no-on-call model; the daily GitHub health check is enough |
| **Larger fixtures (1–5 GB)** | R2 storage ≈ USD 0.075/month per 5 GB, but objects > 512 MB bypass the cache on all non-Enterprise plans | "Big file" download tests | Not recommended: abuse surface and cache bypass; speed-test hosts already exist |
| **Paid design / logo** | one-off USD 50–300 | Nicer brand | Cosmetic; the wordmark is fine |

**Recommended paid footprint**: USD 0 until Phase 3; then USD 5/month for Workers Paid. Optional USD 0.05/month for the Glacier backup. Everything else stays free. Annual total including the domain: ≈ USD 13 (Phase 1–2) → ≈ USD 75 (Phase 3+).
