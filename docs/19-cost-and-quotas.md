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

> **Measured in M2.4 (probe run 4), and it changes which control is doing the work.**
> The two controls this section assumes are **404s cached for 3 minutes** and **the rate
> limit bounding volume**. The first does not exist: `edge_ttl.mode: respect_origin` with
> no `Cache-Control` from R2 on a 404 leaves nothing to respect, so 404s are not cached
> at all (`03` §3, RISK-22). The second works, and counts cache hits — but it is a bound
> on **sustained** volume, not on short bursts: 600 requests at 156 req/s completed with
> no 429 on one run, while another was blocked ~5 s in at request 547.
>
> **The headline numbers below are unchanged**, because scenario 1 already assumes every
> request is an R2 read. What changed is that the rate limit is now the *only* bound, so
> its enforcement latency is the thing that matters rather than a caching mitigation that
> was never real.

Conventions: R2 Class B reads at USD 0.36 per million after the 10 M free tier; the free tier is subtracted in every row; detection latency is the daily health/cost check (≤ 1 day) plus the weekly session to act (≤ 7 days). Query strings are excluded from the cache key, so `?random` busting costs nothing; the remaining read-amplification vectors are unique non-existent paths (each a 404 read cached 3 minutes), distinct `Origin` values (each a cache entry) and many IPs below DDoS thresholds. **Assumption [VERIFY in M2.4]:** a GET for a missing key is billed as a Class B operation. R2's pricing FAQ exempts only unauthorized (401) requests and says nothing about 404s, so the model conservatively counts them; M2.4 measures it (`loremfile usage` before and after 1,000 probe 404s). If 404s turn out to be free, the first two rows below shrink to almost nothing.

| Scenario | Reads / cost | Stop condition |
|---|---|---|
| One IP requesting unique 404 paths at the rate-limit ceiling (30 rps) for 30 days | 77.8 M reads → 67.8 M billable ≈ USD 24 | `cost` issue on day 1–2; ASN/IP block in the weekly session → ≈ USD 5–6 |
| 1,000 IPs × 1 rps unique paths (below DDoS detection) for 7 days | 605 M reads ≈ USD 214 for the week; USD 930/month if never stopped | `cost` issue on day 1 (5 M crossed within 2 hours); custom rule blocking paths outside known prefixes or Under Attack mode; big red button within the week bounds it to ≈ USD 30–220 |
| Legitimate viral usage: 10 M requests/day, 97 % hit ratio | 9 M reads/month ≈ USD 0 | None needed |
| 500 distinct embedding origins × 400 P1 fixtures × ~30 data centres (worst-case fragmentation) | 6 M reads once, then cached ≈ USD 0 | None needed; Smart Tiered Cache keeps it lower |

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
