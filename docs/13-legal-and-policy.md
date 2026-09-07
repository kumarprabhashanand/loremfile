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
> loremfile.dev sets no cookies, runs no analytics scripts and has no accounts. Requests are served by Cloudflare, which processes IP addresses and request metadata to deliver and protect the service; Cloudflare's privacy policy applies to that processing. We look at aggregated statistics (request counts, countries, referrers) that Cloudflare provides; these do not identify individuals. If you email us, we keep the email for as long as needed to answer. No data is sold or shared.

Rationale: no personal data is collected by us; no consent banner is required; GDPR/CCPA obligations are limited to Cloudflare's processor role and the mailbox.

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
- Law-enforcement requests: forward to Cloudflare's processes as appropriate; the project holds no user data.

## 8. Jurisdiction and export

The service is content-neutral, hosts synthetic files, and uses no cryptographic export-controlled software beyond standard TLS. No known country-specific restriction applies. If a jurisdiction blocks Cloudflare or `.dev`, nothing can be done at this budget.

## 9. Accessibility statement (`/docs/faq#accessibility`)

The site targets WCAG 2.1 AA; report issues on GitHub.

## 10. Governance

- Ownership: the domain, Cloudflare account and GitHub repository belong to the owner (Q-01). The maintainer role may be delegated; the credentials never leave the owner's control.
- Contributions: by opening a PR, contributors agree that generator code is MIT and any resulting fixtures are CC0 (`CONTRIBUTING.md` says so; no CLA process).
- Succession: if the owner stops maintaining, the repository and documentation allow anyone to run a mirror; the domain may be transferred to a maintainer by the owner's choice.
