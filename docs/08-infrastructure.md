# 08 — Infrastructure (Cloudflare)

Everything runs in one Cloudflare account, one zone (`loremfile.dev`), one R2 bucket. The owner performs the one-time manual steps in §2; everything else is declarative JSON under `infra/` applied by `loremfile infra apply` and checked by `loremfile infra audit`.

## 1. Inventory

| Resource | Name / value | Managed by |
|---|---|---|
| Domain | `loremfile.dev`, Cloudflare Registrar, auto-renew on, DNSSEC on | Owner (purchase), apply.py (DNSSEC) |
| Zone | `loremfile.dev`, Free plan | Owner (created automatically with the purchase) |
| R2 bucket | `loremfile-public`, location hint `auto` (or `ENAM`/`WEUR` — Q-04) | Owner via wrangler once |
| R2 custom domain | `loremfile.dev` (apex) attached to the bucket, enabled, min TLS 1.2 | Owner once |
| Bucket CORS | policy in `infra/r2-cors.json` | Owner once via wrangler (admin token); audited live by CI |
| Bucket locks | `infra/r2-locks.json`: one indefinite lock rule per `{format}/` prefix (storage-level immutability) | Owner once via wrangler (admin token); audited by `infra audit` via the read-only R2 API if permitted, otherwise monthly by eye |
| URL normalization | Rules → Settings → Normalize incoming URLs: **on** (default) | Owner verifies; audit.py reads it if the API permits **[VERIFY]** |
| DNS | apex record created by R2; `www` CNAME; Email Routing MX + SPF; DMARC | apply.py (`www`, `_dmarc`), Email Routing UI (MX/SPF) |
| Zone settings | `infra/zone-settings.json` | apply.py |
| Rulesets | `infra/rulesets/*.json` (6 phase files, §5) | apply.py |
| Bot settings | `infra/bot-management.json` | apply.py (falls back to a dashboard step if the token lacks permission — see §6) |
| Email Routing | `hello@`, `security@`, `dmarc@` → owner's mailbox | Owner once |
| Notifications | HTTP DDoS alert, Registrar expiry (Usage Based Billing only if the account type offers it, Q-20) | Owner once |
| API tokens | T1 zone CI token; T2 R2 object token; T3 setup admin token (not stored in CI); T4 read-only analytics token | Owner creates; runbook rotates |

## 2. One-time manual setup (owner, ~45 minutes)

> **Progress, 2026-09-08.** Steps 1–3 and 5 are done. Step 4 (DNSSEC), step 7 (bucket,
> apex, CORS) and step 14 (repository variables) were applied through the Cloudflare MCP
> API session rather than a T3 token, so **steps 6 and 8 — create and then delete a T3
> setup token — were not needed and should be skipped.** No admin token ever existed on
> a machine, which is the outcome those two steps were protecting.
>
> Applied and verified: DNSSEC `pending` with the zone already signed (SOA carries an
> RRSIG; Cloudflare Registrar publishes the DS automatically); bucket `loremfile-public`
> (location `auto` resolved to EEUR, Standard class); apex `loremfile.dev` attached with
> min TLS 1.2; CORS exactly as §7; the `pub-*.r2.dev` URL confirmed **disabled**;
> `curl -sI https://loremfile.dev/` returns a Cloudflare 404. Repository variables
> `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_ZONE_ID` are set.
>
> **Lock rules (step 7's fourth command) are deliberately deferred to M2.** They make a
> prefix permanently immutable, and M3 is still adding formats; applying them now would
> force the lift-and-re-add ceremony of `11` §7.9 step 2b for every new format.
>
> Still outstanding and owner-only: steps 9, 10, 10b (tokens T1/T2/T4 — the API session
> cannot mint tokens, `/user/tokens` returns `9109 Unauthorized`, which is correct),
> step 11 (Email Routing, blocked on Q-07), step 12 (notifications) and step 13 (bot
> settings, if `apply.py` cannot set them).
>
> **The account holds two unrelated zones**, `mcpreflex.dev` and `shameher.com`. Every
> call above was scoped to the `loremfile.dev` zone id and both were verified unchanged
> afterwards. Anything applied to this zone in future must be scoped the same way.



Do these in order. Each step says how to verify it.

1. **Cloudflare account hygiene.** Sign in → My Profile → Authentication: enable 2FA with a hardware key or passkey **and** an authenticator app; download and store recovery codes offline. Verify: 2FA badge shown.
2. **Payment method.** Billing → Payment info: add a card (required for Registrar even at USD 0 Cloudflare spend). Verify: card listed.
3. **Buy the domain.** Domain Registration → Register Domains → search `loremfile.dev` → purchase (1 year, auto-renew on, WHOIS redaction on by default). This is the one purchase the API cannot do. Verify: Domain Registration → Manage Domains shows the domain; Websites shows the zone `loremfile.dev` on the Free plan with Cloudflare nameservers.
4. **DNSSEC.** Websites → loremfile.dev → DNS → Settings → Enable DNSSEC (Registrar domains publish the DS automatically). Verify (after ~1 h): `dig +dnssec loremfile.dev SOA` returns `RRSIG`; or https://dnsviz.net.
5. **Enable R2.** R2 Object Storage → accept terms (free tier, no card charge). Verify: R2 overview loads.
6. **Create T3 setup token (temporary).** My Profile → API Tokens → Create Token → Custom: permissions `Account → Workers R2 Storage → Edit`, `Zone → Zone → Read`, `Zone → DNS → Edit` for zone `loremfile.dev`; TTL 1 day. Use it only for steps 7–9 from your own machine; delete it afterwards.
7. **Create the bucket, attach the apex, set CORS** (from a shell with `CLOUDFLARE_API_TOKEN=<T3>` and Node 20+ installed):
   ```bash
   npx wrangler@<pinned version, the current 4.x> r2 bucket create loremfile-public
   npx wrangler@<pinned> r2 bucket domain add loremfile-public --domain loremfile.dev --zone-id <ZONE_ID> --min-tls 1.2   # dashboard equivalent: R2 → bucket → Settings → Custom Domains → Add
   npx wrangler@<pinned> r2 bucket cors set loremfile-public --file infra/r2-cors.wrangler.json                          # dashboard equivalent: bucket → Settings → CORS policy → Add
   npx wrangler@<pinned> r2 bucket lock set loremfile-public --file infra/r2-locks.json                                  # one indefinite lock per format prefix (§7b); dashboard: bucket → Settings → Bucket lock rules
   ```
   Pin the wrangler version instead of `@latest` because this shell holds an admin token. Also run `curl -s -H "Authorization: Bearer $T3" https://api.cloudflare.com/client/v4/user/tokens/permission_groups` and paste the zone permission names for redirect rules, bot management, DNSSEC and cache settings into step 9 (the dashboard token builder labels them differently across plans).
   Attaching the apex **replaces** any existing A/AAAA records at the root with the R2 record (observed behaviour). Verify: `curl -sI https://loremfile.dev/` returns a Cloudflare response with a 404 (expected until the site is uploaded), and in R2 → bucket → Settings the **r2.dev public URL is disabled** (it must stay disabled; the custom domain is the only public path). CORS and headers are verified in M2.4 by the probe workflow, not here.
8. **Delete T3.** My Profile → API Tokens → delete.
9. **Create T1 (zone CI token).** Custom token, name `loremfile-ci-zone`, permissions: `Zone → Zone Settings → Edit`, `Zone → Transform Rules → Edit`, `Zone → Cache Rules → Edit`, `Zone → Zone WAF → Edit`, `Zone → Cache Purge → Purge`, `Zone → DNS → Edit`, `Zone → Zone → Read`, `Zone → Single Redirect → Edit`, and `Zone → Bot Management → Edit` if listed. **Corrected 2026-09-08 against the live token builder:** the entry is **Single Redirect**, not "Dynamic Redirect"; and **do not add `Zone → Config Rule`** — that is Configuration Rules (`http_config_settings`), a phase `apply.py` never writes. The six phases it does write are `http_ratelimit`, `http_request_cache_settings`, `http_request_dynamic_redirect`, `http_request_firewall_managed`, `http_request_transform` and `http_response_headers_transform`; rate limiting rules are part of WAF, so `Zone WAF: Edit` is expected to cover `http_ratelimit`. **To watch at M2.3:** Cloudflare's cache-rules page also lists `Account Rulesets → Edit` and `Account Filter Lists → Edit`. Those are account-scoped and would widen the token past this one zone, so T1 stays zone-only; if `apply.py` gets a 403 on the cache phase, add them then, with the error as evidence; zone resources: include `loremfile.dev` only; client IP filtering: none; TTL: 180 days (set an end date). §6 lists every endpoint apply.py calls with the fallback when a permission is missing. Copy the token into the GitHub `production` environment secret `CLOUDFLARE_API_TOKEN` (see `09`). Verify: `curl -s -H "Authorization: Bearer $T" https://api.cloudflare.com/client/v4/user/tokens/verify` → `"status":"active"`.
10. **Create T2 (R2 object token).** R2 → Manage R2 API Tokens → Create: name `loremfile-ci-r2`, permission **Object Read & Write**, specify bucket `loremfile-public` only, TTL 180 days. Copy the S3 **Access Key ID** and **Secret Access Key** into the GitHub secrets `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY`. Verify: the uploader's `--dry-run` lists the bucket. Whether this permission can delete objects is not stated in the docs; M2.4's `probe --down` establishes it (**[VERIFY]**) — with bucket locks in place it only matters for `_probe/` and tombstoned keys.
10b. **Create T4 (read-only analytics token).** Custom token, name `loremfile-ci-analytics`, permissions `Account → Account Analytics → Read` and `Zone → Analytics → Read` for `loremfile.dev`, TTL 365 days. GitHub secret `CLOUDFLARE_ANALYTICS_TOKEN`. Used only by `health.yml` to read R2 operations and zone traffic; it can change nothing.
11. **Email Routing.** Websites → loremfile.dev → Email → Email Routing → Enable → add destination (your mailbox, confirm the verification mail) → routes: `hello@`, `security@`, `dmarc@` → destination. Accept the automatic MX/SPF DNS records. Verify: send a mail to `hello@loremfile.dev`.
12. **Notifications.** Notifications → Add: `DDoS – HTTP DDoS Attack Alert` (all plans) and `Registrar – domain expiring` if listed; destination: your email. The `Billing – Usage Based Billing` notification exists only for Pro+ plans and pay-as-you-go accounts (Q-20) — add it if the dashboard offers it, but the cost control is the automated daily usage check in `health.yml` (ADR-025), not this notification.
13. **Bot settings (dashboard, if apply.py cannot).** Security → Bots: Bot Fight Mode **off**; Security → Settings (or Security → Bots): Block AI bots **off** / "Do not block" (including the post-2026-09-15 "training"/"agent" crawler defaults); "Managed robots.txt" **off**. Verify: `curl -A "python-requests/2.32" https://loremfile.dev/manifest.json` is not challenged (200 after the first deploy).
14. **Hand the rest to CI.** Fill `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_ZONE_ID` (Websites → loremfile.dev → Overview, right column) as GitHub variables. From here on `deploy.yml` applies §3–§5.

## 3. Zone settings — `infra/zone-settings.json`

```json
{
  "always_use_https": "on",
  "ssl": "strict",
  "min_tls_version": "1.2",
  "tls_1_3": "on",
  "http3": "on",
  "0rtt": "on",
  "ipv6": "on",
  "brotli": "on",
  "opportunistic_encryption": "on",
  "cache_level": "aggressive",
  "websockets": "off",
  "rocket_loader": "off",
  "email_obfuscation": "off",
  "automatic_https_rewrites": "off",
  "hotlink_protection": "off",
  "browser_check": "off",
  "security_level": "essentially_off",
  "server_side_exclude": "off",
  "development_mode": "off",
  "early_hints": "off",
  "polish": "off",
  "mirage": "off"
}
```

Why the "off" list matters: each of `rocket_loader`, `email_obfuscation`, `automatic_https_rewrites`, `server_side_exclude`, `polish`, `mirage` rewrites response bodies, which would change fixture bytes; `hotlink_protection` blocks the product's purpose; `browser_check` and `security_level` challenge non-browser clients (curl, CI, agents). Browser TTL is governed by the cache rule (`browser_ttl.mode: respect_origin`), not by the zone-level `browser_cache_ttl` setting, whose "respect existing headers" value is reported to be rejected by the API on non-Enterprise zones. `polish`/`mirage` are Pro features: apply.py skips settings whose GET reports `editable: false`; audit.py only complains if such a setting is not `off`.

## 4. Bot management — `infra/bot-management.json`

```json
{ "fight_mode": false, "ai_bots_protection": "disabled", "is_robots_txt_managed": false, "cf_robots_variant": "off", "content_bots_protection": "disabled" }
```

Applied with `PUT /zones/{zone_id}/bot_management`. `cf_robots_variant: "off"` and `content_bots_protection: "disabled"` matter because Cloudflare's defaults for zones onboarded after 2026-09-15 block "training" and "agent" AI crawlers, and agents are an audience of this site. `is_robots_txt_managed: false` is essential: the managed robots.txt feature prepends Cloudflare content to our `robots.txt`. If the T1 token cannot write this endpoint (permission name varies by plan — **[VERIFY]** during M2), apply.py prints the dashboard instructions from §2 step 13 and continues; audit.py still reads the state if it can and otherwise checks behaviour live.

## 5. Rulesets — `infra/rulesets/`

Each file is the complete desired list of rules for one phase's zone entry-point ruleset. apply.py `PUT`s `https://api.cloudflare.com/client/v4/zones/<ZONE_ID>/rulesets/phases/<phase>/entrypoint` with `{"rules": [...]}` (creating the entry point if the GET returns 404). Rule `ref` values are stable identifiers so audits can diff by ref.

### 5.1 `http_request_dynamic_redirect.json` (Single Redirects)

```json
{ "rules": [
  { "ref": "www_to_apex", "description": "www → apex, keep path and query", "enabled": true,
    "expression": "(http.host eq \"www.loremfile.dev\")",
    "action": "redirect",
    "action_parameters": { "from_value": { "status_code": 301,
      "target_url": { "expression": "concat(\"https://loremfile.dev\", http.request.uri.path)" },
      "preserve_query_string": true } } }
] }
```

### 5.2 `http_request_transform.json` (URL rewrites; 2 of the 10 free transform rules)

```json
{ "rules": [
  { "ref": "root_index", "description": "/ → /index.html", "enabled": true,
    "expression": "(http.request.uri.path eq \"/\")",
    "action": "rewrite", "action_parameters": { "uri": { "path": { "value": "/index.html" } } } },
  { "ref": "dir_index", "description": "trailing slash → index.html", "enabled": true,
    "expression": "(ends_with(http.request.uri.path, \"/\") and http.request.uri.path ne \"/\")",
    "action": "rewrite", "action_parameters": { "uri": { "path": { "expression": "concat(http.request.uri.path, \"index.html\")" } } } }
] }
```

### 5.3 `http_response_headers_transform.json` (3 of the 10, plus an optional fourth below)

```json
{ "rules": [
  { "ref": "files_headers", "description": "all objects with an extension (fixtures, discovery files, assets)", "enabled": true,
    "expression": "(http.request.uri.path contains \".\" and not ends_with(http.request.uri.path, \"/index.html\"))",
    "action": "rewrite", "action_parameters": { "headers": {
      "X-Content-Type-Options": { "operation": "set", "value": "nosniff" },
      "Cross-Origin-Resource-Policy": { "operation": "set", "value": "cross-origin" },
      "Timing-Allow-Origin": { "operation": "set", "value": "*" },
      "X-Robots-Tag": { "operation": "set", "value": "noindex" } } } },
  { "ref": "active_content_sandbox", "description": "inert CSP for markup fixtures", "enabled": true,
    "expression": "((ends_with(http.request.uri.path, \".html\") and not ends_with(http.request.uri.path, \"/index.html\")) or ends_with(http.request.uri.path, \".htm\") or ends_with(http.request.uri.path, \".xhtml\") or ends_with(http.request.uri.path, \".svg\") or ends_with(http.request.uri.path, \".xml\"))",
    "action": "rewrite", "action_parameters": { "headers": {
      "Content-Security-Policy": { "operation": "set", "value": "sandbox; default-src 'none'; img-src https://loremfile.dev data:; media-src https://loremfile.dev; style-src 'unsafe-inline'; font-src https://loremfile.dev" } } } },
  { "ref": "site_pages_headers", "description": "site pages (extensionless keys and index.html)", "enabled": true,
    "expression": "((not http.request.uri.path contains \".\") or ends_with(http.request.uri.path, \"/index.html\"))",
    "action": "rewrite", "action_parameters": { "headers": {
      "Content-Security-Policy": { "operation": "set", "value": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'" },
      "X-Frame-Options": { "operation": "set", "value": "DENY" },
      "Referrer-Policy": { "operation": "set", "value": "strict-origin-when-cross-origin" },
      "X-Content-Type-Options": { "operation": "set", "value": "nosniff" },
      "Permissions-Policy": { "operation": "set", "value": "camera=(), microphone=(), geolocation=()" } } } }
] }
```

Notes: the `site_pages_headers` expression groups `(not A) or B` explicitly; the Rules language would evaluate it the same way without the parentheses (documented precedence: `not` first, then `and`, `xor`, `or`), but a security-relevant rule should not depend on a reader knowing that. `http.request.uri.path` in this phase reflects the URL-rewrite result, so `/` and `/pdf/` are seen as `/index.html` and `/pdf/index.html` and get site headers. `assets/site.<hash>.css` gets file headers (harmless). The sandbox CSP also lands on `sitemap.xml` and RSS/Atom fixtures, which is harmless for non-document consumers and desirable when opened in a browser.

These suffix tests rely on Cloudflare's **URL normalization** (Rules → Settings → Normalize incoming URLs, on by default) so that `/html/basic%2Ehtml` is evaluated as `/html/basic.html`; the setting is part of the desired state and audit probes request encoded paths. As belt-and-braces, a fourth header rule keyed on the response type is added if the field is available on the Free plan (**[VERIFY]** in M2.3; the `http.response.content_type` field is documented for response-phase rules):

```json
  { "ref": "active_content_sandbox_by_type", "description": "sandbox CSP by response Content-Type (belt and braces)", "enabled": true,
    "expression": "(http.request.uri.path contains \".\" and not ends_with(http.request.uri.path, \"/index.html\") and (http.response.content_type contains \"text/html\" or http.response.content_type contains \"xml\"))",
    "action": "rewrite", "action_parameters": { "headers": {
      "Content-Security-Policy": { "operation": "set", "value": "sandbox; default-src 'none'; img-src https://loremfile.dev data:; media-src https://loremfile.dev; style-src 'unsafe-inline'; font-src https://loremfile.dev" } } } }
```

That makes 6 of the 10 free transform rules if the optional rule is added (2 URL rewrites + 4 header rules); 5 without it.

### 5.4 `http_request_cache_settings.json` (1 of 10 cache rules)

```json
{ "rules": [
  { "ref": "cache_everything_respect_origin", "description": "cache all objects; TTL from object Cache-Control", "enabled": true,
    "expression": "(http.host eq \"loremfile.dev\")",
    "action": "set_cache_settings",
    "action_parameters": { "cache": true, "edge_ttl": { "mode": "respect_origin" }, "browser_ttl": { "mode": "respect_origin" },
      "cache_key": { "custom_key": { "query_string": { "exclude": "*" } } } } }
] }
```

"Ignore query string" in the cache key is available on all plans (the API form documented for it is `exclude: "*"`; if the API rejects that literal, use `{"all": true}` — M2.3 confirms). With it, `?anything` requests share the cached object and cost no extra R2 read.

Also enable **Tiered Cache → Smart Tiered Cache** (Caching → Tiered Cache) — apply.py does this via `PATCH /zones/{zone_id}/cache/tiered_cache_smart_topology_enable {"value":"on"}` (endpoint and Free-plan availability verified); it reduces R2 reads by funnelling misses through one upper-tier data centre, which matters because every distinct embedding origin has its own cache entry. Dashboard fallback: Caching → Tiered Cache → Smart Tiered Cache → On.

### 5.5 `http_ratelimit.json` (the single free rule)

```json
{ "rules": [
  { "ref": "per_ip_burst", "description": "300 req / 10 s per IP per data centre, verified bots exempt. The path test is a tautology: Free-plan rate-limit expressions may only reference the path and verified-bot fields, and an expression is mandatory. Do not simplify it away.", "enabled": true,
    "expression": "(starts_with(http.request.uri.path, \"/\") and not cf.client.bot)",
    "action": "block",
    "ratelimit": { "characteristics": ["cf.colo.id", "ip.src"], "period": 10, "requests_per_period": 300, "mitigation_timeout": 10 } }
] }
```

Free-plan constraints (verified): 1 rule, period 10 s, mitigation timeout 10 s, IP characteristic, expression fields limited to path and verified-bot. In the API the dashboard's "IP" characteristic is `ip.src` **plus `cf.colo.id`, which Cloudflare documents as mandatory in every rule's `characteristics` list on every plan** (counting is therefore per IP per data centre; never use `cf.colo.id` in the expression itself). 300/10 s = 30 rps per IP per data centre, comfortably above real usage and below abuse.

### 5.6 `http_request_firewall_managed.json`

```json
{ "rules": [
  { "ref": "free_managed_ruleset", "description": "Cloudflare Free Managed Ruleset", "enabled": true,
    "expression": "true", "action": "execute",
    "action_parameters": { "id": "77454fe2d30c4220b5701f6fdfb893ba" } }
] }
```

Free zones already receive this ruleset; apply.py first `GET`s the entry point and only adds the rule if no rule executes that ID. If the API rejects the write on the Free plan, apply.py records "managed by Cloudflare by default" and audit.py verifies via `GET`. The ID is confirmed by listing `GET /accounts/<ACCOUNT_ID>/rulesets` and matching `name == "Cloudflare Free Managed Ruleset"`; apply.py does this lookup rather than trusting the constant.

## 6. `apply.py` and `audit.py`

Common: read `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID`, `CLOUDFLARE_ACCOUNT_ID` from env; retry with backoff on 429/5xx; never delete resources it did not define (rulesets are `PUT` in full because each file is the complete desired list for that phase — the phases used are owned by this project; other phases are never touched). Both run from GitHub Actions (`infra.yml`, `deploy.yml`, `audit.yml`); nobody needs the tokens locally.

`apply.py [--dry-run]`:
1. Zone settings: `GET /zones/{id}/settings`; for each key in `zone-settings.json`, if `editable` and value differs → `PATCH /zones/{id}/settings/{key}`.
2. Bot management: `GET`, `PUT` if different; on 403 print §2 step 13 and continue (exit code stays 0 but the summary marks it "manual").
3. DNSSEC: `GET /zones/{id}/dnssec`; if not `active` → `PATCH {"status":"active"}`.
4. DNS: ensure `www` CNAME → `loremfile.dev` proxied; ensure `_dmarc` TXT `v=DMARC1; p=reject; rua=mailto:dmarc@loremfile.dev; adkim=s; aspf=s`; ensure the SPF TXT contains `include:_spf.mx.cloudflare.net` **only if** Email Routing already created it (never create SPF from scratch; Email Routing owns it). Never delete records.
5. Rulesets: for each phase file, GET entry point (404 → create via `POST /zones/{id}/rulesets` with `kind: zone, phase`), then `PUT …/phases/{phase}/entrypoint` with the rules. For `http_request_firewall_managed`, first list `GET /accounts/{account_id}/rulesets` to resolve the Free Managed Ruleset ID by name and skip if the entry point already executes it.
6. Tiered cache: `PATCH …/cache/tiered_cache_smart_topology_enable`.
7. URL normalization: `GET`; if not `type: cloudflare, scope: incoming` → write it (or print the dashboard path when the API refuses).
8. Print a summary table: resource → unchanged / updated / skipped(reason) / manual.

`infra/dns.json` (desired records; apply.py step 4 reads it rather than hard-coding):

```json
{ "records": [
  { "type": "CNAME", "name": "www", "content": "loremfile.dev", "proxied": true },
  { "type": "TXT", "name": "_dmarc", "content": "v=DMARC1; p=reject; rua=mailto:dmarc@loremfile.dev; adkim=s; aspf=s" }
], "expected_managed": ["apex R2 record", "MX ×3 (Email Routing)", "TXT SPF (Email Routing)"] }
```

`infra/token-expiry.json` (dates only, never secrets; updated by the rotation procedure `11` §7.3; read by `health.yml` to open `rotation-due` issues 30 days ahead):

```json
{ "T1": { "name": "loremfile-ci-zone", "expires": "2027-03-06" }, "T2": { "name": "loremfile-ci-r2", "expires": "2027-03-06" }, "T4": { "name": "loremfile-ci-analytics", "expires": "2027-09-06" } }
```

Endpoints, expected token permissions and the fallback when the API answers 403 (all confirmed or corrected in M2.3, which records the outcome in this table):

| Step | Endpoint | Permission expected | 403 fallback |
|---|---|---|---|
| 1 | `/zones/{id}/settings/*` | Zone Settings: Edit | dashboard: Speed / Security / Scrape Shield toggles |
| 2 | `/zones/{id}/bot_management` | Bot Management: Edit **[VERIFY]** | §2 step 13 |
| 3 | `/zones/{id}/dnssec` | DNS: Edit (or Zone Settings: Edit) **[VERIFY]** | DNS → Settings → Enable DNSSEC |
| 4 | `/zones/{id}/dns_records` | DNS: Edit | DNS → Records |
| 5 | `/zones/{id}/rulesets/phases/http_request_dynamic_redirect/entrypoint` | **Zone → Single Redirect → Edit** (**resolved 2026-09-08**: the token builder has no "Dynamic Redirect" entry; Cloudflare's own docs name *Zone → Single Redirect → Edit* as the required permission for this phase. The API phase kept the older internal name) | Rules → Redirect Rules |
| 5 | `…/http_request_transform`, `…/http_response_headers_transform` | Transform Rules: Edit | Rules → Transform Rules |
| 5 | `…/http_request_cache_settings` | Cache Rules: Edit | Caching → Cache Rules |
| 5 | `…/http_ratelimit`, `…/http_request_firewall_managed` | Zone WAF: Edit | Security → WAF |
| 6 | `/zones/{id}/cache/tiered_cache_smart_topology_enable` | Cache Settings: Edit (endpoint verified) | Caching → Tiered Cache |
| 7 | `/zones/{id}/url_normalization` (read; write only if off) | Zone Settings: Edit **[VERIFY endpoint]** | Rules → Settings → Normalize incoming URLs |
| health | GraphQL Analytics `r2OperationsAdaptiveGroups` (T4) | Account → Account Analytics: Read **[VERIFY in M0.4 when T4 is created]** | Read R2 usage in the dashboard |
| purge | `/zones/{id}/purge_cache` | Cache Purge | Caching → Configuration → Purge |

`audit.py [--strict]`: performs every GET, diffs against desired state, and additionally runs behavioural probes against production: `GET /` is HTML; `GET /pdf/` equals `GET /pdf`; header rules present on a fixture, a markup fixture and a page; the sandbox CSP is present on `/html/basic%2Ehtml` and `/svg/simple-shapes%2Esvg` (normalization check); a warm-cache CORS check (GET without `Origin`, then with `Origin: https://example.org` → `access-control-allow-origin: *`, `cf-cache-status` MISS then HIT on repeat); `OPTIONS` preflight returns `access-control-allow-origin: *`; `www` redirects; `X-Robots-Tag` absent on `/pdf`; bucket lock rules present for every format prefix (via `GET /accounts/{account_id}/r2/buckets/{bucket}/lock` if T1/T4 may read it, else skipped with a warning); the DNS zone contains only the expected records (apex R2 record, `www`, MX ×3, SPF, DMARC) and lists any others as findings. Settings the token cannot read are reported as warnings and do not fail the run unless `--strict`. Exit 1 on any real difference. Runs after every deploy and weekly.

## 7. `infra/r2-cors.json` (S3 shape) and `infra/r2-cors.wrangler.json` (wrangler shape)

S3 shape, for reference and for `audit.py`'s behavioural check:

```json
[ { "AllowedOrigins": ["*"], "AllowedMethods": ["GET", "HEAD"], "AllowedHeaders": ["*"],
    "ExposeHeaders": ["Content-Length", "Content-Range", "Content-Type", "Content-Disposition", "ETag", "Accept-Ranges", "Last-Modified"],
    "MaxAgeSeconds": 86400 } ]
```

Wrangler shape (`rules[].allowed.{origins,methods,headers}`, `exposeHeaders`, `maxAgeSeconds`) is the same policy in the format `wrangler r2 bucket cors set` reads; keep both files in sync (a unit test checks equivalence).

## 7b. `infra/r2-locks.json` — bucket lock rules (storage-level immutability)

R2 bucket locks "prevent the deletion and overwriting of objects" under a prefix, indefinitely if configured so. One rule per format prefix (generated from the catalog by `loremfile infra locks --write`; committed):

```json
{ "rules": [
  { "id": "lock-pdf",  "enabled": true, "prefix": "pdf/",  "condition": { "type": "Indefinite" } },
  { "id": "lock-png",  "enabled": true, "prefix": "png/",  "condition": { "type": "Indefinite" } },
  { "id": "lock-edge", "enabled": true, "prefix": "edge/", "condition": { "type": "Indefinite" } },
  { "id": "lock-locktest", "enabled": true, "prefix": "_locktest/", "condition": { "type": "Indefinite" } }
] }
```

The committed file has one entry for every format directory in `05` §3 (≈ 65 rules; the three above are illustrative) plus the `_locktest/` rule, which exists so that M2.4 can prove lock behaviour: the probe writes one 1-byte object `_locktest/probe` once (it then stays forever, harmless) and verifies that overwriting and deleting it are refused. Fixture prefixes are never probed that way.

Consequences: `upload --fixtures` can only ever add objects; a leaked T2 cannot overwrite or delete a fixture; site keys (root, `docs/`, `legal/`, `assets/`, discovery files) and `_probe/` are outside every locked prefix and stay writable; a takedown requires the owner to remove the affected prefix's rule with an admin token, delete the object, and re-add the rule (`11` §7.8) — the right amount of ceremony for a legal removal. The maximum number of lock rules per bucket is not stated in the docs (**[VERIFY]** in M0.4: if the API rejects ≈ 65 rules, lock the largest formats first and record the rest as a known gap in `17`). Adding a new format later means adding its rule (owner step with T3, listed in `11` §7.9).

## 8. Cloudflare features that must stay OFF (checked by audit.py where readable, otherwise in the monthly checklist)

Read and enforced by `infra audit` via zone settings: Rocket Loader, Email Address Obfuscation, Automatic HTTPS Rewrites, Server-side Excludes, Hotlink Protection, Browser Integrity Check, Polish, Mirage, Early Hints, plus (via the bot-management endpoint, if readable) Bot Fight Mode, Block AI Bots, Managed robots.txt, and URL normalization (must stay **on**). Cloudflare Fonts and Speed Brain have zone-setting IDs (`fonts`, `speed_brain`) that M2.3 confirms **[VERIFY]** and then adds to `zone-settings.json` as `off`. Checked manually in the monthly checklist because they are separate products without a simple setting: Zaraz (never enabled), Web Analytics automatic injection (never add the site), Crawler Hints, Under Attack Mode (only during an incident).

## 9. What the Free plan cannot do (so nobody tries)

Regex in rules; excluding the `Origin` header from the cache key or adding headers/cookies to it (ignoring or sorting the query string **is** available); more than one rate-limiting rule; host-header override; custom error pages; Cache Reserve without paying; caching objects > 512 MB. Purge by URL, hostname, tag, prefix and purge-everything are all available on Free (100 operations per request).



