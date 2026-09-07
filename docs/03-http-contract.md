# 03 — HTTP Contract

This is the public interface. Changes to anything marked **stable** require a new catalog major version and a changelog entry; the old behaviour keeps working.

## 1. URL scheme (stable)

```
https://loremfile.dev/{format}/{name}
```

- `format`: `^[a-z0-9]+$`, one of the formats in `05-fixture-catalog.md` (e.g. `pdf`, `mp4`, `bin`, `edge`, `hls`).
- `name`: `^[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+)+$` — lowercase kebab-case descriptor followed by one or more extensions. Examples: `a4-3pages.pdf`, `3-text-files.tar.gz`, `people-1000.parquet`.
- HLS is the one nested case and has its own grammar: `hls/{variant}/(index|master)\.m3u8` and `hls/{variant}/seg-[0-9]{3}\.ts` where `variant` matches the descriptor grammar (`720p-10s`, `multi-bitrate`). The catalog validator applies this exception; `filename` in `Content-Disposition` and `ext` in the manifest are derived from the last path segment.
- No uppercase, no spaces, no underscores, no query parameters needed. Query strings are ignored by the origin and excluded from the edge cache key, so `?v=1` is harmless (ADR-013).
- Names are permanent. A fixture is never renamed or deleted (except for a legal takedown, see `13-legal-and-policy.md` §7; even then the manifest keeps a tombstone).

### Descriptor grammar

Descriptors are ordered tokens separated by `-`:

```
[variant]-[dimension|duration|count|size]-[qualifiers]
```

| Token type | Examples | Rule |
|---|---|---|
| dimension | `640x480`, `1080p`, `4k`, `a4`, `letter` | Width×height in pixels, or a well-known label |
| duration | `5s`, `30s`, `10min` | Seconds or minutes |
| count | `3pages`, `10rows`, `100k-rows`, `1000-files`, `10frames` | Unit spelled out |
| size | `1kb`, `10mb`, `100mb` (decimal) · `1kib`, `10mib`, `100mib` (binary) | Exactness class from catalog |
| boundary | `10mib-plus-1`, `10mb-minus-1` | Exactly nominal ± 1 byte |
| encoding | `utf8-bom`, `utf16le`, `latin1`, `crlf` | Text fixtures |
| codec/profile | `vp9`, `h264-baseline`, `320kbps`, `24bit-96k` | Media fixtures |
| dataset | `people-1000`, `orders-100k` | Shared synthetic datasets |

## 2. Methods (stable)

| Method | Behaviour |
|---|---|
| `GET` | Returns the object. Supports `Range`, `If-None-Match`, `If-Modified-Since`. |
| `HEAD` | Same headers as GET, no body. |
| `OPTIONS` | CORS preflight, answered per bucket CORS policy (§5). |
| Others | Not part of the contract; Cloudflare/R2 return 4xx/405. |

## 3. Status codes (stable)

| Code | When |
|---|---|
| 200 | Object found |
| 206 | Valid `Range` satisfied |
| 304 | Conditional request matched |
| 301 | `www.` host → apex; (Phase 3 only) `/random/*` |
| 404 | Unknown key. Body is a short plain/XML message from R2 and is **not** part of the contract. R2 sends no `Cache-Control` on 404, so Cloudflare caches it for its default of 3 minutes per data centre (M2.4 probes this, and measures whether R2 bills a 404 as a Class B read — assumed yes in the cost model). |
| 416 | Unsatisfiable range |
| 429 | Rate limited (300 requests / 10 s per IP). Retry after 10 s. |
| 403 | WAF managed rule matched (only for exploit-shaped requests) |

## 4. Response headers

### 4.1 On every fixture (stable)

| Header | Value | Source |
|---|---|---|
| `Content-Type` | Exact MIME from the catalog, e.g. `application/pdf`, `text/csv; charset=utf-8`, `application/vnd.apache.parquet` | Object metadata set at upload |
| `Content-Length` | Exact byte count (matches `manifest.bytes`). Guaranteed because `no-transform` disables edge compression for fixtures. | R2 |
| `Cache-Control` | `public, max-age=31536000, immutable, no-transform` | Object metadata |
| `Content-Disposition` | `inline; filename="{last path segment}"` | Object metadata |
| `Accept-Ranges` | `bytes` | R2 |
| `ETag` | Opaque. Do **not** assume it is an MD5; use `manifest.sha256`. | R2 |
| `Last-Modified` | Upload time; informational | R2 |
| `Access-Control-Allow-Origin` | `*` (only when request has `Origin`) | Bucket CORS policy |
| `Access-Control-Expose-Headers` | `Content-Length, Content-Range, Content-Type, Content-Disposition, ETag, Accept-Ranges, Last-Modified` | Bucket CORS policy |
| `X-Content-Type-Options` | `nosniff` | Response header rule H1 |
| `Cross-Origin-Resource-Policy` | `cross-origin` | Rule H1 |
| `Timing-Allow-Origin` | `*` | Rule H1 |
| `X-Robots-Tag` | `noindex` | Rule H1 (raw files stay out of search results; pages are indexed instead). The same rule reaches every path containing a dot, so `manifest.json`, `sitemap.xml`, `robots.txt`, `llms.txt`, `llms-full.txt`, `/assets/*` and `security.txt` also carry `noindex`; that is accepted (search engines ignore it on sitemaps/robots, and the social image is not needed in image search). |
| `cf-cache-status` | `HIT`/`MISS`/… informational | Cloudflare |

### 4.2 Additionally on active-content fixtures (`.html`, `.htm`, `.xhtml`, `.svg`, `.xml`) (stable)

| Header | Value | Why |
|---|---|---|
| `Content-Security-Policy` | `sandbox; default-src 'none'; img-src https://loremfile.dev data:; media-src https://loremfile.dev; style-src 'unsafe-inline'; font-src https://loremfile.dev` | `sandbox` makes the document inert when opened directly: no script execution, no form submission, no plugins, opaque origin. The explicit host allow-list (not `'self'`, which is meaningless for an opaque origin) lets the fixture's own images, media, inline styles and fonts still render so people can eyeball it. Scripts stay blocked because `sandbox` forbids them and no `script-src` is granted. |

The sandbox CSP is deliberately **not** applied to PDFs or media: browsers' built-in PDF viewers have failed to render PDFs served with a restrictive CSP (Chromium issue 40328564, Mozilla bug 1582115), so PDFs carry no CSP at all.

### 4.3 On site pages (extensionless paths) (may evolve)

`Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-Content-Type-Options: nosniff`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`.

## 5. CORS (stable)

Bucket CORS policy (S3 syntax). It is applied **once by the owner** with an admin token (`08` §2 step 7 and §7) because bucket configuration needs the R2 admin permission that neither CI token has; `infra audit` verifies the live behaviour:

```json
[
  {
    "AllowedOrigins": ["*"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["Content-Length", "Content-Range", "Content-Type", "Content-Disposition", "ETag", "Accept-Ranges", "Last-Modified"],
    "MaxAgeSeconds": 86400
  }
]
```

Consequences: `fetch()` from any origin works; `<video>`, `<audio>`, `<img crossorigin>` work; `Range` requests from browsers work (the `Range` request header is covered by `AllowedHeaders: *`); sites using `Cross-Origin-Embedder-Policy: require-corp` can embed fixtures because of `Cross-Origin-Resource-Policy: cross-origin`.

## 6. Caching semantics

- Fixtures are immutable: clients and intermediaries may cache for a year. Bust nothing; the URL is the version.
- Site and discovery files: 5-minute TTL. Deploys purge them explicitly.
- **Query strings**: the cache rule excludes the query string from the cache key (`08` §5.4), so `?v=1` and `?v=2` share one cache entry and cost no extra R2 read. Query strings never change behaviour.
- **`Origin` header**: Cloudflare's default cache key also includes the request's `Origin` header, so a fixture fetched from three different web origins occupies three cache entries and costs three R2 reads on first use. This is normal CORS behaviour and is accounted for in the cost model (`19` §2).
- `Vary`: not used.
- Compression: fixtures are served byte-exact (`no-transform`). Site HTML/CSS/JS may be gzip/brotli-encoded by the edge; their `Content-Length` may then differ from the stored size.

## 7. Immutability policy (stable)

1. A path, once present in `manifest.json` on `main`, is permanent.
2. Its bytes, `sha256`, `bytes`, `mime` are frozen. CI enforces this (lock check).
3. To fix a defective fixture, add a new fixture (e.g. `a4-3pages-v2.pdf`), set `supersededBy` on the old entry, mark it `deprecated: true`, keep serving it.
4. Only a legal takedown may remove an object; the manifest entry then becomes `{"status": "removed", "reason": "…", "removed_at": …}` and the site marks it.
5. The `manifest.json` document itself, `sha256sums.txt`, the site and `index.json` files are mutable.

## 8. Client guidance (published on the site)

- Verify downloads with `sha256sum -c sha256sums.txt --ignore-missing`.
- Prefer HEAD for size checks (`Content-Length` equals `manifest.bytes`).
- Do not rely on `ETag` equalling MD5.
- Query strings are ignored; they neither bust the cache nor change the response.
- Rate limit: keep below 30 requests/second per IP; CI jobs that need more should download once and cache locally.
- Bandwidth is free for us; still, please do not use fixtures as a general-purpose CDN speed test in a loop.

## 9. Examples

```bash
# 10 MiB + 1 byte, to test a "10 MiB max" upload limit
curl -fsSLO https://loremfile.dev/bin/10mib-plus-1.bin

# HEAD for size
curl -sI https://loremfile.dev/pdf/a4-3pages.pdf | grep -i content-length

# Range
curl -s -r 0-99 -o part.bin -D - https://loremfile.dev/mp4/720p-5s.mp4 | grep -i content-range

# Verify
curl -fsSL https://loremfile.dev/sha256sums.txt | grep 'pdf/a4-3pages.pdf' | sha256sum -c
```
