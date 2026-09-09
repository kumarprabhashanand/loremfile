# 11 — Operations Runbook

Operating model: no on-call, no pager. Automation raises GitHub issues; a human (or an agent in a scheduled session) looks at them **weekly**. Everything here is written so that it can be executed by someone who has never operated the service.

## 1. Where things are

| Need | Location |
|---|---|
| Production | https://loremfile.dev |
| Source, issues, CI | https://github.com/<OWNER>/loremfile |
| Health status | Open issues labelled `health` (none = healthy) |
| Cloudflare zone analytics | Cloudflare dashboard → Websites → loremfile.dev → Analytics & Logs |
| R2 usage | Cloudflare dashboard → R2 → loremfile-public → Metrics; and R2 → Overview (account usage) |
| Billing | Cloudflare dashboard → Billing |
| Domain | Cloudflare dashboard → Domain Registration |
| Backups | GitHub Releases (delta and snapshot archives) |
| Desired state | `infra/` in the repository |

## 2. Weekly session (≤ 60 minutes)

1. **Triage issues** labelled `health`, `infra-drift`, `determinism`, `security`, `fixture-request`. For each: read the latest comment; follow the matching procedure in §7.
2. **Merge Dependabot PRs** that are green. For Python or Docker updates the PR must include the regenerated lock and new digest (CI enforces). If determinism tests fail on a toolchain bump, open a `determinism` issue and do not merge.
3. **Look at usage** (2 minutes, A): read the latest line of `ops-log.md` on the `ops-log` branch (`https://github.com/<OWNER>/loremfile/blob/ops-log/ops-log.md`), written automatically every Monday by `health.yml` (requests/day, bandwidth, cache hit ratio, R2 Class B month-to-date, top paths). Target hit ratio ≥ 95 % zone-wide; R2 Class B < 5 M/month. If the line is missing, `health.yml` is not running — check Actions.
4. **Check spend** (O, monthly is enough): Billing → current usage should be USD 0.00 apart from the domain. The agent cannot see billing; the `cost` issue from `health.yml` is the automated proxy.
5. **Fixture requests**: label, reply with the naming grammar, or implement if small.
6. **Close the session** by noting anything unusual in the `notes` column of the latest `ops-log.md` line (push to the `ops-log` branch).

## 3. Monthly (first weekly session of the month, +30 minutes)

- (A) Review the `determinism` audit result (workflow `audit.yml`, first Monday).
- (O, 10 minutes; the agent cannot see account settings or billing) Run the hardening checklist from `10-security.md` §5 (read-only spot check: 2FA on, tokens as inventoried, Registrar lock, auto-renew; the readable "must be off" settings via `infra audit`, the manual ones listed in `08` §8 by eye).
- (O) Check the card on file is not expiring within 60 days.
- (A) Verify the latest GitHub Release archive is downloadable and `sha256sum -c` passes for 3 random entries.
- (A) Add the monthly success-metric line (`00-overview.md` §6: GitHub code-search count, referrer hosts) under the automated weekly lines in `ops-log.md` on the `ops-log` branch (a direct push; the branch is unprotected by design).

## 4. Quarterly (+60 minutes)

- Rotate T1 and T2 if they are within 60 days of expiry (§7.3).
- Restore drill lite: download one release archive, extract, compare hashes with the manifest (§7.6 step 1–3 only).
- Review the roadmap (`14`) and pick the next phase-2 batch.
- Review the risk register (`17`) for changed likelihoods.

## 5. Yearly

- GitHub disables scheduled workflows in public repositories after 60 days without repository activity. The Monday commit to the `ops-log` branch prevents that; if `health.yml` ever stops (no ops-log line for two weeks), open Actions → `health` → **Enable workflow**, then check why the heartbeat stopped.

- Domain renewal happens automatically ~30 days before expiry; confirm in Domain Registration that the expiry moved forward.
- `security.txt` `Expires` is refreshed by every deploy; if no deploy happened in 11 months, trigger `deploy.yml` manually.
- Re-read `13-legal-and-policy.md` for anything the world changed (new TLD policies, Cloudflare terms).

## 6. Alerts and what they mean

| Signal | Source | Meaning | Procedure |
|---|---|---|---|
| Issue `Health check failing` opened/updated | `health.yml` | Some URL/headers/hash/expiry/site-integrity check failed | §7.1 |
| Issue `R2 operations above threshold` | `health.yml` usage step | Month-to-date Class B reads > 5 M | §7.4 |
| Issue `Token rotation due` | `health.yml` | A token expires within 30 days | §7.3 |
| Issue `Infra drift detected` | `audit.yml` | Cloudflare state differs from `infra/` | §7.2 |
| Issue `Determinism drift` | `audit.yml` monthly | Regenerating a published fixture produced different bytes | §7.5 |
| Email: Cloudflare Usage Based Billing (only if the account is pay-as-you-go/Pro+, Q-20) | Cloudflare | Spend threshold crossed | §7.4 |
| Email: HTTP DDoS attack alert | Cloudflare | Mitigation triggered automatically | Read analytics; usually nothing to do; §7.4 if cost follows |
| Email: domain expiring / renewal failed | Registrar | Payment problem | Fix card → Renew now |
| Dependabot security alert | GitHub | Vulnerable dependency | Merge the update PR this week; toolchain bump PR if needed |
| `deploy.yml` failed | GitHub | Deploy stopped at a step | §7.7 |

## 7. Procedures

### 7.1 Health check failing

1. Open the issue; read the JSON report attached in the latest comment: which checks failed (`missing_object`, `content_length_mismatch`, `hash_mismatch`, `header_missing`, `status`, `rdap_expiry`, `tls_expiry`, `security_txt_expiry`, `timeout`).
2. `timeout`/`status 5xx` for many paths → check https://www.cloudflarestatus.com. If Cloudflare has an incident, wait; the check auto-closes when green.
3. `missing_object` → the key is absent in R2. Run `deploy.yml` manually (`workflow_dispatch`); `build --missing-in-bucket` regenerates and uploads the missing fixtures (never overwrites). If `manifest check` fails there with a hash diff, the toolchain has drifted for that fixture: run `infra.yml` in `restore` mode with the latest release archive instead. If objects keep disappearing, rotate T2 and read the R2 audit log — with bucket locks in place this should be impossible.
4. `hash_mismatch` or `content_length_mismatch` on a fixture → treat as an incident (`10` §6): run `infra.yml` in `audit` mode plus `verify-live --mode full` (any machine, no credentials needed) to list all affected paths; restore them by running `infra.yml` in `restore` mode with the latest release archive URL and the affected paths (`upload --restore` writes only where the live hash differs from the manifest); rotate T2.
5. `header_missing` → run `infra.yml` in `audit` mode; if drift, run it in `apply` mode.
6. `rdap_expiry` < 45 days → Domain Registration → check auto-renew and card; renew manually if needed.
7. `security_txt_expiry` → trigger a deploy.
8. Comment on the issue with what you did; the next green run closes it.

### 7.2 Infra drift

`loremfile infra audit` output lists each differing setting. If the change was intentional (made in the dashboard during an incident), port it into `infra/` via PR. Otherwise run `infra.yml` in `apply` mode and investigate who changed it (Cloudflare → Manage Account → Audit Log).

### 7.3 Rotate a token

1. Cloudflare → create the new token with exactly the permissions in `08` §2 (T1, T4) or R2 → Manage API tokens (T2). Set the expiry 180 days out (365 for T4) and record the new expiry date in `infra/token-expiry.json` (dates only, no secrets; `health.yml` reads it to open the `rotation-due` reminder 30 days ahead) in a small PR.
2. GitHub → Settings → Environments → production → update the secret(s).
3. Run `infra.yml` in `audit` mode (T1) or `deploy.yml` manually with no changes (T2, everything is skipped) or `health.yml` (T4).
4. Delete the old token in Cloudflare. The new expiry date is already in `infra/token-expiry.json` (step 1); note the rotation in the `notes` column of the next ops-log line.

### 7.4 Cost spike or abuse

1. Read the `cost` issue (it lists Class B reads per day and the top paths and status codes from zone analytics). Cloudflare Analytics → Traffic and Security → Analytics show the ASNs, countries and whether requests hit existing objects or 404s.
2. If the pattern is unique non-existent paths: Security → WAF → Custom rules (5 free) → block requests whose path does not start with a known prefix, e.g. `not (starts_with(http.request.uri.path, "/pdf/") or starts_with(http.request.uri.path, "/png/") or … or http.request.uri.path eq "/" or starts_with(http.request.uri.path, "/docs/") …)` — `loremfile infra allowlist-rule` prints the full expression from the catalog. Port it into `infra/` via PR if it stays.
3. If a single ASN/IP range: custom rule blocking `ip.src.asnum` or `ip.src in {…}`.
4. If volumetric: Security → Settings → Under Attack Mode for a few hours (this challenges all clients, including agents — use only as a last resort).
5. R2: the free tier is 10 M reads/month; overage is USD 0.36 per million — a spike of 100 M reads costs USD 32 (90 M billable). If spend is escalating and the above doesn't stop it, temporarily disable the custom domain (R2 → bucket → Settings → Custom Domains → Disable). This is the "big red button": the site goes dark with TLS/connection errors (no maintenance page is possible with HSTS-preloaded `.dev`), new R2 reads stop, and already-cached objects keep serving until they expire.
6. Post-mortem: open an issue with timeline, cost, and whether the default rate limit should change.

### 7.5 Determinism drift

The monthly audit found that regenerating fixture X with the current toolchain yields different bytes. Published bytes are canonical and unaffected. Actions: (a) read the diff summary; (b) if caused by a dependency update, note it in the fixture's `notes` field in the catalog (informational) and keep going; (c) if caused by a generator bug, fix the generator only if it does not change any *new* fixture's expected output; never regenerate published fixtures. Close the issue with the explanation.

### 7.6 Restore drill / disaster recovery

Honest recovery targets: **content and a mirror hostname within one working day**; **`loremfile.dev` itself only as fast as Cloudflare support restores the account**, because the domain is registered there (ADR-020, RISK-19; Q-06 would change this). The repository README is the out-of-band channel: it always states the current canonical host, and the site's Rules page says so.

1. From GitHub Releases download every archive since the first release (delta tarballs) or the latest snapshot plus later deltas; if a fixture was redacted, its tombstone is in `sha256sums.txt`.
2. Extract into one directory; run `sha256sum -c sha256sums.txt --ignore-missing` (all OK).
3. Missing fixtures (if any archive was lost) can be regenerated with `loremfile build --all --only <paths>` in the toolchain image of the release (`toolchain_image` in that manifest); verify hashes.
4. New Cloudflare account (or the recovered one): repeat `08` §2 (domain if recoverable, otherwise a fallback hostname; bucket; custom domain; CORS; tokens; **apply the lock rules only after the restore upload**, or the restore cannot write), then run `infra.yml` in `restore` mode with the archive URL(s) (or, if GitHub is also gone, `loremfile upload --from-dir <dir> --fixtures --site` from a machine that holds temporary tokens created for the occasion), then `apply` mode, then `verify-live --mode full`. Step 4's unknowns (apex attach, CORS, locks, tokens, `infra apply` on a fresh zone) are exactly the steps rehearsed in M0.4 and M2 — record their durations then; a full rehearsal on a throwaway zone is optional (≈ USD 10 for a domain).
5. If the domain is lost for good, publish the new host in the README and on the mirror's home page; nothing else can be done at this budget.
Practise steps 1–3 before launch (M5.5) and record the time taken.

### 7.7 Deploy failed

Read the failing step. `manifest check` hash diff → a generator drifted for a fixture that had to be regenerated (rare; both use the same image) → re-run; if persistent, open a `determinism` issue and restore the affected paths from the release archive via `infra.yml` `restore` mode. `upload --fixtures` refusing to overwrite → somebody changed a published entry; revert the PR. `upload --apply-removals` refused by a bucket lock → the takedown ordering in §7.8 was not followed (lift the lock first). `infra apply` errors → token permissions (see `08` §6); fix and re-run with `workflow_dispatch`. `verify-live smoke` failing right after upload → wait 60 s (propagation) and re-run the job.

### 7.8 Takedown (legal request or policy violation)

1. Verify the request is legitimate (see `13` §7). Record it in a private issue (security advisory draft) with the request text.
2. Owner (T3 admin token or dashboard): remove the bucket-lock rule for the affected format prefix — `npx wrangler r2 bucket lock remove loremfile-public --id lock-<format>`. Without this step the delete in step 4 is refused by the storage layer.
3. Open a PR that sets `status: removed` with `removed: {reason, removed_at}` on the catalog entry, deletes its `generator_params` (and the generator branch if the code itself embodies the problem), runs `loremfile manifest update` (the entry becomes a tombstone, `04` §1.5), and adds a CHANGELOG line.
4. Merge: `deploy.yml` runs `upload --apply-removals`, which deletes the object and purges its URL; the site shows the tombstone.
5. Owner re-adds the lock rule (`npx wrangler r2 bucket lock set loremfile-public --file infra/r2-locks.json` restores the full set).
6. Run `infra.yml` in `redact` mode with the path (`09` §10) so the bytes leave the GitHub Release assets.
7. Reply to the requester.

### 7.9 Add a fixture (normal change)

1. Add the entry to `catalog/{format}.yaml` and to `docs/05-fixture-catalog.md`.
2. **Inside the pinned toolchain image** (a host ffmpeg or Pillow will produce different bytes for media and images): `loremfile build --only <path> && loremfile validate --only <path> && loremfile manifest update` → commit `manifest.json` and `sha256sums.txt` changes (only additions). CI regenerates the fixture from the catalog and checks your committed entry against it; if it differs, the CI summary prints the exact entries to commit. **For media, the image alone is not enough**: the encoders dispatch on CPU features, so your machine and CI can legitimately disagree (`06` §4). CI is the authority — save the printed entries to a file and run `loremfile manifest adopt --from <file>`, which refuses anything already published on the base branch.
2b. A **new format** also needs a bucket-lock rule: `loremfile infra locks --write` updates `infra/r2-locks.json`, and the owner applies it once with `wrangler r2 bucket lock set` (T3) before the deploy — add the owner step to the PR description.
3. Update `CHANGELOG.md`. Open a PR; CI must be green; merge; deploy runs; tag a release when convenient.

### 7.10 Data-subject request (access, erasure, objection, or the same right under another law)

1. **We hold nothing but the email thread the requester started** — no accounts, no cookies, no analytics identifiers and no server logs (`13` §3a). Search the mailbox for their address and check the retention schedule in `13` §3a; that is the whole search.
2. **Cloudflare holds the edge request logs** as our processor and we cannot query them. If the request concerns those, ask the requester for the approximate time and the URL, forward the request to Cloudflare, and tell the requester you have done so and when.
3. **Reply within one month** using the template below, then record the request, what was held and the reply date in a private GitHub security advisory draft (never in a public issue — the request itself is personal data). If the requester asks for erasure of the thread, delete it and say so.

Response template:

> Thank you for your request of {date}.
>
> loremfile.dev has no accounts, sets no cookies, runs no analytics and keeps no server logs, so the only personal data we hold about you is this email thread — your address and what you wrote — which we delete no later than 24 months after the last message, or sooner if you ask.
>
> Requests to the site are delivered by Cloudflare, Inc., which processes IP addresses and request metadata as our processor; we have no access to those raw logs. {If applicable: we forwarded your request to Cloudflare on {date}.}
>
> Our privacy notice is at https://loremfile.dev/legal/privacy. You may complain to your supervisory authority — in the EU the one where you live or work, in the UK the Information Commissioner's Office.

## 8. `ops-log.md` format (on the `ops-log` branch)

```
| date | requests/day | bandwidth/day | cache hit % | R2 class B (month) | spend (month) | notes |
```
