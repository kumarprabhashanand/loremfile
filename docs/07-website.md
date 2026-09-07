# 07 — Website

The site is static HTML rendered at build time from the manifest and stored in the same bucket. It has three jobs: (1) let a human find and copy a fixture URL in under ten seconds, (2) rank for the search queries people already use, (3) document the contract.

## 1. Information architecture

| URL | Page | Notes |
|---|---|---|
| `/` | Home | One-line pitch, search box (client-side filter over a slim `search-index.json` — path, bytes, description only, ≈ 40 KB — fetched on the first keystroke; progressive enhancement), grid of families → formats with counts (`family` field), "Popular" list (the 10 fixed URLs in `05` §8), copy buttons, three usage snippets (curl, JS fetch, Python) |
| `/{format}` and `/{format}/` | Format page | H1 with the SEO title from the catalog; intro from `site/content/formats/{format}.md`; table: name (link), size (human + exact on hover), key props, description, copy button; `<details>` per row with curl/HTML snippet; related formats from the catalog's `related` list; tombstone lines for removed fixtures; JSON-LD per `04` §10 |
| `/formats` | All formats | Table of every format with counts and default MIME |
| `/docs/getting-started` | Quick start | URL scheme, examples, verification |
| `/docs/http-contract` | Rendered `docs/03-http-contract.md` | The only two repository docs published on the site are 03 and 04 |
| `/docs/manifest` | Rendered `docs/04-manifest-and-discovery.md` | |
| `/docs/naming` | `site/content/pages/naming.md`: the grammar from `03` §1, size units (decimal vs binary) explained with the boundary files | |
| `/docs/faq` | `site/content/pages/faq.md`: hotlinking allowed? rate limits? why no `?download`? why noindex on files? can I mirror? accessibility statement | |
| `/docs/contributing` | Rendered `CONTRIBUTING.md` | Links to the fixture-request issue template |
| `/docs/security-policy` | `site/content/pages/security-policy.md` = `10` §7 verbatim | Referenced by security.txt |
| `/docs` and `/legal` | Index pages listing their children (so `/docs/` and `/legal/` resolve after the trailing-slash rewrite) | |
| `/legal/license`, `/legal/terms`, `/legal/privacy` | Legal | Full texts in `13` §1.1, §2, §3 |
| `/changelog` | Catalog versions | From `CHANGELOG.md` |
| `/status` | Static page explaining that a daily health check runs and linking to the open `health` issues in GitHub | No dynamic status (nothing to host it) |

## 2. Design requirements

- **No JavaScript required** for any content. JS adds: copy-to-clipboard buttons, the client-side search/filter on the home page, and "show curl" toggles. All degrade to plain links.
- **No external requests**: system font stack (`system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif` and `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`), inline SVG icons, one CSS file, one JS file, both content-hashed under `/assets/`.
- **Theme**: light and dark via `prefers-color-scheme`; tokens on `:root`; WCAG AA contrast (≥ 4.5:1 body, ≥ 3:1 large text).
- **Responsive**: tables scroll horizontally inside their container on narrow screens; the page never scrolls horizontally.
- **Accessibility**: skip link, landmark roles, visible focus, `aria-live` for "Copied", labels on the search input, table headers with `scope`.
- **Performance**: each page ≤ 60 KB HTML gzip; CSS ≤ 15 KB; JS ≤ 10 KB; the 100k-row-family pages are still small because the table lists files, not rows.
- **Brand**: wordmark "loremfile" in monospace, a simple SVG mark (a page outline with "Lorem" text) **inlined as `<svg>` in the templates** — never loaded via `<object>`/`<iframe>`, because `.svg` responses carry the sandbox CSP; `assets/mark.svg` exists only for the Open Graph fallback and README badges.
- **Trailing slashes**: canonical URLs have none. The edge rewrite makes `/`, `/{format}/`, `/docs/` and `/legal/` work; deeper paths with a trailing slash (`/docs/faq/`) return 404 by design.

## 3. SEO

- Titles follow the search demand: "Sample PDF files for testing (free, CC0, direct links) — loremfile.dev". H1 repeats it. Meta description mentions "hotlink", "no signup", "stable URLs".
- Canonical `<link>` to the non-trailing-slash form. `www` redirects at the edge.
- `sitemap.xml`, `robots.txt` (allow all), Open Graph and Twitter card tags with a static `/assets/og.png` (generated 1200×630 test card with the wordmark; it is itself a fixture-like image but lives under `/assets`).
- JSON-LD exactly as specified in `04` §10.
- Internal linking: every format page links to its `related` formats (catalog field; defaults in `05` §8) and to the naming page.
- Content per format page: 120–250 words of genuinely useful text (what the format is used for, gotchas the fixtures cover) — not filler. See §5 for authoring.
- Raw fixtures carry `X-Robots-Tag: noindex` so search results land on pages, which have the context and copy buttons.

## 4. Build

`loremfile site build`:

1. Load manifest, catalog (for descriptions and SEO titles), `CHANGELOG.md`, and `docs/*.md` chosen for publication. The build is **deterministic for a given commit**: the only date it uses is the committer date of `HEAD` (`git log -1 --format=%cI`), which feeds `sitemap.xml` `lastmod` and `security.txt` `Expires` (commit date + 365 days); nothing reads the clock, so `health.yml` can rebuild the deployed commit and use its hashes as the site-integrity baseline.
2. Render Jinja2 templates in `site/templates/` (`base.html`, `home.html`, `format.html`, `formats.html`, `doc.html`, `legal.html`, `changelog.html`, `status.html`, `404.html` (only used locally; R2 cannot serve it)).
3. Markdown → HTML via `markdown-it-py` with tables and fenced code; **no raw HTML passthrough** from docs.
4. Write to `build/site/`: `search-index.json`, `favicon.ico` and `apple-touch-icon.png` (rendered from the brand mark; referenced by `<link rel="icon">` / `<link rel="apple-touch-icon">` on every page), `index.html`, `{format}` (extensionless copy) + `{format}/index.html` (byte-identical), `docs` + `docs/index.html`, `docs/{slug}`, `legal` + `legal/index.html`, `legal/{slug}`, `changelog`, `formats`, `status`, `assets/site.<hash>.css`, `assets/site.<hash>.js`, `assets/og.png`, `assets/mark.svg`, `manifest.json` (copied from the repository root), `formats.json`, `sha256sums.txt`, `llms.txt`, `llms-full.txt`, `sitemap.xml`, `robots.txt`, `.well-known/security.txt`, `schema/manifest-v1.json`, `{format}/index.json` (site build is the single writer of these per-format files).
5. Post-build checks (`tests/site/`, see `12` §3): every internal link resolves to a built key or a manifest path; no `http://` or external hosts except the allow-list (`github.com/<OWNER>/loremfile`, `creativecommons.org`, `llmstxt.org`, `developers.cloudflare.com`); every page has exactly one H1, a `<title>`, a meta description, `lang="en"`; HTML validates with `html5lib` parse without errors; `assets/*.css` referenced with the right hash.

## 5. Content authoring

All site copy is drafted by the engineer/agent in M4.2 and lives as Markdown in the repository: `site/content/formats/{format}.md` (one per format that has at least one P1 fixture; 120–250 words: what the format is, what people test with it, which gotchas the fixtures cover, cross-links), `site/content/pages/{getting-started,naming,faq,security-policy}.md`, `site/content/home.md`. AI-drafted text is acceptable; the acceptance rule is that every factual statement about a fixture matches the catalog (a test cross-checks every fixture path mentioned in content against the manifest) and that no page is shorter than 120 words. The owner may edit any text; edits go through PRs like everything else.

## 6. Copy for the home page (first draft, to be edited during M4)

> **loremfile.dev** — sample files you can hotlink.
> Free, CC0, stable forever. PDFs, images, audio, video, office documents, data files, archives, fonts, text in every encoding, exact-size blobs, and deliberately broken edge cases. Open CORS, byte ranges, a SHA-256 manifest. No ads, no signup, no keys.
>
> `curl -O https://loremfile.dev/pdf/a4-3pages.pdf`

Then: format grid → "Popular right now" (static list) → "For agents" box linking `llms.txt` and `manifest.json` → "Rules" (immutability, rate limit, licence, and: "if this host is ever unavailable, the repository README states the current canonical host") → footer (source, security, legal).

## 7. Analytics

None on the page. Usage is read from Cloudflare zone analytics (request counts, bandwidth, cache ratio, top paths, referrers) which need no JavaScript and set no cookies. This keeps the privacy policy one paragraph and the CSP strict.
