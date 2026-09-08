# 13 — Legal and Policy

This is not legal advice; it is the set of rules the project follows and the texts the site publishes. Keep the texts short and honest.

## 1. Licences

| What | Licence | File |
|---|---|---|
| Generated fixtures (everything served under `/{format}/`) | **CC0 1.0 Universal** (public domain dedication) | `LICENSES/CC0-1.0.txt`; stated in `manifest.json`, on every format page, in `llms.txt` |
| Source code, templates, docs | **MIT** | `LICENSE` |
| Site text and images | CC BY 4.0 (attribution to loremfile.dev) | `/legal/license` (text in §1.1) |
| Third-party components | Their own licences, listed in `THIRD_PARTY.md` (Debian ffmpeg and codecs — LGPL/GPL, used as tools not redistributed; DejaVu fonts — Bitstream Vera licence, glyphs rasterised into a few images/PDFs; Python libraries — permissive) | `THIRD_PARTY.md` |

Why CC0 for fixtures: users must be able to embed, redistribute, modify and commit fixtures into any codebase, including proprietary and GPL ones, without attribution. CC0 removes every question.

### 1.1 Licence page (`/legal/license`) — full text

> **Licences**
> **Files.** Every file served under a format path (for example `/pdf/…`, `/bin/…`, `/edge/…`) is dedicated to the public domain under the [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/) deed. You may copy, modify, distribute and use them for any purpose, commercially or not, without asking permission or giving credit.
> **Code.** The generators, site and tooling are open source under the MIT licence at https://github.com/<OWNER>/loremfile.
> **This website's text and graphics** are licensed CC BY 4.0; attribute "loremfile.dev".
> **Trademarks and third parties.** Format names (PDF, MP4, …) belong to their owners and are used descriptively. No third-party media is redistributed; see THIRD_PARTY.md in the repository for the tools used to generate files.

## 2. Terms of use (`/legal/terms`) — full text

> **loremfile.dev terms of use**
> 1. The files on this site are released under CC0 1.0. You may use them for anything, without attribution.
> 2. The service is provided "as is", without warranty of any kind. We aim to keep every published URL working with identical bytes indefinitely, but we make no guarantee of availability or continuity.
> 3. Please keep automated traffic below 30 requests per second per client. We may rate-limit, block or otherwise restrict clients that degrade the service for others.
> 4. Do not use this service to distribute content you do not own, to test attacks against third parties, or in any way that violates law. The service hosts no user content and offers no upload.
> 5. We may add files at any time. We remove files only for legal reasons; removed URLs are documented in the manifest.
> 6. Contact: hello@loremfile.dev · https://github.com/<OWNER>/loremfile

## 3. Privacy notice (`/legal/privacy`) — full text

> **Privacy**
>
> **Who is responsible.** `<CONTROLLER>` is the controller for the personal data described
> here. Contact: `<CONTACT_EMAIL>`.
>
> **What is processed, and by whom.** loremfile.dev has no server, no accounts, no logins,
> no cookies and no analytics scripts. Every request is answered by Cloudflare's network in
> front of a Cloudflare R2 bucket. To deliver and protect the service, Cloudflare processes:
>
> - your **IP address**;
> - **request metadata**: timestamp, requested URL, HTTP method and status code, bytes
>   served, user agent, referrer, TLS and protocol details, and the approximate country
>   derived from the IP address.
>
> An IP address is personal data. Cloudflare, Inc. does this as our **processor** under the
> Cloudflare Customer Data Processing Addendum; we are the controller. Cloudflare's own
> privacy policy describes what it does with that data as a controller for its own security
> purposes.
>
> **Legal basis.** Article 6(1)(f) GDPR — our legitimate interests in delivering the file you
> asked for, keeping the service available, and protecting it from abuse (rate limiting,
> blocking attack traffic). There is no profiling, no advertising, no automated
> decision-making and no tracking across sites. You may object; see **Your rights**.
>
> **What the operator sees.** **We retain no server logs — there is no server.** We read only
> aggregated statistics that Cloudflare produces: request counts, bandwidth, cache hit ratio,
> countries, referrer hosts, top paths and status codes. Those aggregates identify nobody and
> we do not try to re-identify anyone from them.
>
> **Email.** If you write to us we process your address and whatever you put in the message,
> in order to answer you (Art. 6(1)(f); Art. 6(1)(c) where a legal notice obliges us to act).
> We delete ordinary correspondence **no later than 24 months** after the last message in the
> thread. Records of legal notices, takedown requests and law-enforcement requests are kept
> for **6 years** after the request is resolved, so we can show why a file was removed.
>
> **Sharing.** Nothing is sold, rented, or shared for advertising — ever. The only recipient
> of request data is Cloudflare, Inc. as our processor. If you choose to open an issue or a
> pull request, GitHub, Inc. processes what you write there under its own terms and it is
> public.
>
> **International transfers.** Cloudflare is a US company and serves requests from data
> centres worldwide, so this data leaves your country. Cloudflare certifies under the
> EU-U.S. Data Privacy Framework, its UK extension and the Swiss-U.S. Data Privacy Framework.
> Where the Framework does not cover a transfer, the Cloudflare Customer DPA incorporates the
> EU Standard Contractual Clauses (Module Two, controller to processor), amended by the UK
> Addendum and the Swiss modifications. Details in §3a.
>
> **Your rights.** Under the GDPR and the UK GDPR you have the right of access,
> rectification, erasure, restriction and portability, and the right to object to processing
> based on legitimate interests. Write to `<CONTACT_EMAIL>`; we answer within one month.
> In practice we hold nothing that identifies you except an email thread you started, so an
> access or erasure request is normally answered with exactly that. For the data Cloudflare
> processes on our behalf, send us the approximate time and the URL and we will pass the
> request to Cloudflare. You may also complain to your supervisory authority — in the EU the
> one where you live or work, in the UK the Information Commissioner's Office (ico.org.uk).
>
> **Changes.** This notice lives in the project's public repository; its version history is
> the changelog.

**Placeholders (blocking).** `<CONTROLLER>` (Q-21: named controller vs contact address only)
and `<CONTACT_EMAIL>` (Q-07: which mailbox `hello@`/`security@` route to; the documents
assume `hello@loremfile.dev`) are **not yet decided by the owner**. M4.2 must not render
`/legal/privacy` while either placeholder is unresolved — an unreachable contact address or
an absent controller identity is itself a defect under Art. 13 GDPR. Both are tracked as
open blockers in the "Implementation status" issue.

## 3a. Compliance posture

**Processor agreement.** Cloudflare Customer Data Processing Addendum, **version 6.4,
effective 2026-04-03** (https://www.cloudflare.com/dpa). It forms part of the Self-Serve
Subscription Agreement, states that "the Customer is the Controller … and Cloudflare is a
Processor", and requires affirmative acceptance by someone with authority to bind the
customer.

**Acceptance (M0.6, recorded 2026-09-08).** The DPA is in force for this account: it
forms part of the Self-Serve Subscription Agreement, which the owner accepted when the
Cloudflare account was created, and its own opening clause is what makes that so for
self-serve customers. There is no separate DPA click and Cloudflare exposes no
per-account acceptance record through its API, so what this section cites is the version
in force — **v6.4, effective 2026-04-03** — rather than an acceptance artefact. Cloudflare
publishes DPA revisions that supersede earlier ones, so the current version is the one
that governs, and §8's annual review re-reads it.

No acceptance date is published here. Art. 28 requires a processor contract to exist and
Art. 30(1) lists what the record must contain; neither asks for a date, and the account's
creation date is personal operational metadata that would sit in a public repository for
no compliance benefit. If a supervisory authority ever asks, the date is retrievable from
`GET /accounts/{account_id}` (`created_on`) and Cloudflare support can confirm the
agreement independently.

(Verified 2026-09-07: version, effective date, controller/processor roles, transfer
clauses and the acceptance warranty read from the DPA text itself.)

**Record of processing activities (GDPR Art. 30(1)).** This is the whole record; there is
nothing else.

| # | Art. 30(1) item | Entry |
|---|---|---|
| 1 | Controller and contact details | `<CONTROLLER>`, `<CONTACT_EMAIL>` (Q-21, Q-07) |
| 2 | Joint controller, DPO, EU/UK representative | None. No DPO required (no large-scale or special-category processing, no systematic monitoring); Art. 27 representative not appointed — see §8 |
| 3 | Processing activity | Delivery of a public, read-only static file service (loremfile.dev), and the contact mailbox |
| 4 | Purposes | Serve the requested file; keep the service available; detect and mitigate abuse; answer correspondence and legal notices |
| 5 | Categories of data subject | Visitors and automated clients of loremfile.dev; people who email us or open a GitHub issue |
| 6 | Categories of personal data | IP address; request metadata (timestamp, URL, method, status, bytes, user agent, referrer, TLS/protocol, derived country); email address and message content. No special categories (Art. 9), no criminal-offence data (Art. 10), no data about children sought or knowingly processed |
| 7 | Categories of recipient | Cloudflare, Inc. — processor (CDN, R2 storage, DNS, WAF, Email Routing) and its sub-processors per its published list; GitHub, Inc. — issues and pull requests the person chooses to open, public by design |
| 8 | Third-country transfers | United States and Cloudflare's global network. Safeguards: EU-U.S. DPF, UK extension and Swiss-U.S. DPF; EU SCCs Module Two with the UK Addendum and Swiss modifications where the DPF does not apply (Cloudflare Customer DPA §6) |
| 9 | Erasure time limits | Operator: **no server logs are kept at all**. Email: 24 months after the last message. Legal-notice records: 6 years after resolution. Cloudflare-side edge logs: Cloudflare's own retention policy — the operator has no access to raw logs and stores none |
| 10 | Security measures (Art. 32) | No origin server and no public write path; TLS-only with HSTS; R2 bucket locks make published objects undeletable and unoverwritable; credentials exist only in the GitHub `production` environment and never on a personal machine (`10` §2); hardware-key 2FA on the Cloudflare and GitHub accounts; least-privilege scoped API tokens with expiry dates and quarterly rotation (`11` §7.3); daily automated integrity and health checks; the published files themselves contain no personal data (§5) |

**Retention schedule.**

| Data | Held by | Retention |
|---|---|---|
| IP address and request metadata | Cloudflare (processor) | Cloudflare's own retention policy; the operator neither receives nor stores raw logs |
| Aggregated analytics (counts, bandwidth, hit ratio, countries, referrers, top paths) | Cloudflare dashboard; totals copied into `ops-log.md` | Aggregated, not personal data; the ops-log line is kept indefinitely |
| Email correspondence | The owner's mailbox, via Cloudflare Email Routing | Deleted no later than 24 months after the last message in the thread |
| Legal notices, takedown and law-enforcement requests | Private GitHub security advisory draft plus the mailbox | 6 years after the request is resolved |
| GitHub issues and pull requests | GitHub, public | Public and permanent by design; created voluntarily by the person |
| Published fixtures | R2 bucket | Permanent by design; synthetic, and §5 forbids content identifying a real person |

**Transfer mechanism, in one line.** DPF first; EU SCCs Module Two (with the UK Addendum and
the Swiss modifications) as the fallback — both supplied by the Cloudflare Customer DPA, no
separate paperwork on our side.

**Handling a request.** Runbook `11` §7.10.

## 4. Acceptable use for the project itself

The maintainers will not: add tracking, add ads, sell or paywall access, host anything on behalf of third parties, or use the domain for email marketing.

## 5. Content policy for fixtures (enforced by `validators/policy.py` and PR review)

**Allowed**: synthetic documents, media, data, archives, fonts, text, byte patterns, malformed/truncated/mismatched variants, bounded stress cases (deep nesting, many entries, large dimensions with low entropy) with documented resource needs.

**Forbidden on loremfile.dev** (a separate domain may host some of these in Phase 4 after its own review):
- Malware test strings (EICAR), real malware, exploit proofs-of-concept, files crafted to crash specific software versions.
- Executables of any kind (PE, ELF, Mach-O, scripts marked executable, `.jar` with classes, macros in Office files, `.lnk`, `.scr`, `.msi`, `.apk`, `.dmg`).
- Decompression bombs (ratio > 1000:1) except the documented ZIP64 entry-count case.
- Script-bearing PDFs (`/JavaScript`, `/Launch`, `/OpenAction`), SVGs with `<script>` or event handlers, HTML that imitates a login page or a real brand.
- Anything resembling credentials: private keys written to a file, API keys, JWT secrets, real-looking card numbers (even test PANs), IBANs, national IDs. (The Ed25519 test certificate is signed by a key derived from a public seed; the key is never written, the fixture description says the key is publicly derivable, and the certificate names `fixture.example`, never a real host.)
- Anything that identifies a real person: a real name combined with a real address, contact detail, photo, identifier or biography. Synthetic datasets may combine common first and family names at random with fictional contact details; a coincidental match of a common name with a real city (there will be a "John Smith, Chicago" in 100,000 rows) identifies nobody because every other field is invented. Real organisations' logos; third-party copyrighted text, images, audio, video, fonts.
- Content that is illegal in major jurisdictions or sexual, violent, hateful, or political in nature (fixtures are boring by design).
- Files > 100 MB.

**Gray areas decided**: the `MZ` two-byte prefix in `edge/exe-header-with-txt-extension.txt` is allowed because the file is otherwise text, cannot execute, and is whitelisted by path in the catalog (`policy_exceptions: [mz-prefix]`; the manifest records its hash); an internal-subset DTD is allowed; `../evil.txt` as a zip entry name is allowed because it tests extractor hygiene and contains only lorem text.

## 6. Trademark and naming

"loremfile" is a coined name; no registration is planned. Do not use third-party marks in fixture names (no "adobe", "microsoft", "excel" — use format names like `xlsx`). The site says "PDF", "MP4", "Excel-compatible (.xlsx)" descriptively only where needed.

## 7. Takedown and abuse handling

- Requests arrive via `hello@`/`security@` or GitHub issues. The project hosts no user content, so DMCA-style notices should be rare; if one arrives, verify it identifies a specific URL and a plausible right, then follow runbook §7.8, which removes the object from R2, from every GitHub Release asset, and removes the generator parameters (and generator code if it embodies the content) so the bytes cannot be trivially regenerated. Respond within 7 days.
- Abuse reports about third parties hotlinking fixtures: the fixtures are inert; no action unless a court order or Cloudflare requires it.
- Law-enforcement requests: forward to Cloudflare's processes as appropriate. The project has no accounts and keeps no server logs, so it holds nothing to disclose; Cloudflare holds the edge request logs as our processor (§3a).
- Data-subject requests (access, erasure, objection) follow runbook §7.10, not this procedure.

## 8. Jurisdiction, export and country-specific posture

The service is content-neutral, hosts synthetic files, and uses no cryptographic
export-controlled software beyond standard TLS. If a jurisdiction blocks Cloudflare or
`.dev`, nothing can be done at this budget.

The project's own assessment of the regimes that could reach a free, non-commercial,
globally reachable file service — not legal advice, reviewed annually and whenever the
service changes character (for example if it ever charges money or adds accounts):

| Regime | In scope? | Posture |
|---|---|---|
| **EU GDPR / UK GDPR** | Yes, in principle — visitors in the EU/UK and their IP addresses | Notice in §3, Art. 30 record and DPA in §3a, legal basis Art. 6(1)(f), rights procedure in `11` §7.10. No establishment in the EU or UK. **Art. 27 representative not appointed**: no special-category data, no behavioural monitoring for profiling, no server logs retained, and the only processing is delivery metadata handled by the processor. Revisit if the service becomes commercial or adds any tracking |
| **CCPA / CPRA (California)** | No | The operator is not a "business" under Cal. Civ. Code §1798.140(d): it is not operated for profit and is below all three thresholds — annual gross revenue over USD 25 M (as adjusted for inflation); buying, selling or sharing the personal information of 100,000+ consumers or households; or 50 % or more of revenue from selling or sharing personal information. Nothing is sold or shared, so no "Do Not Sell or Share" link is required |
| **India DPDP Act 2023** | Possibly, extraterritorially (processing connected with offering services to data principals in India) | Only delivery metadata, handled by the processor; no server logs retained; no advertising, no profiling. Data-principal requests are handled by the same procedure as GDPR requests (`11` §7.10). Reassess as the DPDP Rules' obligations come fully into force |
| **Brazil LGPD** | Possibly, extraterritorially | Same posture as GDPR: legitimate-interests basis (Art. 7 IX), no logs retained, same rights procedure and the same contact address |
| **Canada PIPEDA** | No | PIPEDA governs personal information collected in the course of **commercial activity**; this service is free, sells nothing and carries no advertising |
| **China PIPL** | Possibly, extraterritorially | The service is not targeted at, marketed in, or localised for China, does no profiling, and no local representative is filed. Revisit only if that changes |
| **European Accessibility Act** (Directive (EU) 2019/882, applicable since 28 June 2025) | Not as a covered service | The site is not e-commerce, banking, transport, telecoms, e-books or any other Annex I service, and is in any case provided by a micro-enterprise (fewer than 10 people, turnover ≤ EUR 2 M), which Art. 4(5) exempts from the service obligations. WCAG 2.1 AA remains the target regardless (§9) |

## 9. Accessibility statement (`/docs/faq#accessibility`)

The site targets WCAG 2.1 AA; report issues on GitHub.

## 10. Governance

- Ownership: the domain, Cloudflare account and GitHub repository belong to the owner (Q-01). The maintainer role may be delegated; the credentials never leave the owner's control.
- Contributions: by opening a PR, contributors agree that generator code is MIT and any resulting fixtures are CC0 (`CONTRIBUTING.md` says so; no CLA process).
- Succession: if the owner stops maintaining, the repository and documentation allow anyone to run a mirror; the domain may be transferred to a maintainer by the owner's choice.
