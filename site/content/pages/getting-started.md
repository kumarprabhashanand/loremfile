## The URL scheme

Every file lives at `https://loremfile.dev/{format}/{name}`. The format is the first path
segment and the name says what is inside: `pdf/a4-3pages.pdf` is three A4 pages, and
`csv/people-1000.csv` is a thousand rows of synthetic people. There is nothing to sign up for
and no key to send. [Naming and sizes](/docs/naming) explains the grammar.

## Fetch a file

```bash
curl -O https://loremfile.dev/pdf/a4-3pages.pdf
```

A web page on any origin can fetch a file directly: CORS allows `GET` and `HEAD` from every
origin, and byte-range requests work, so a media player can seek. Query strings are ignored,
so `?v=2` neither busts a cache nor changes what you receive.

## Check the size first

```bash
curl -sI https://loremfile.dev/mp4/720p-5s.mp4 | grep -i content-length
```

`Content-Length` equals the `bytes` field in the manifest. Do not treat the `ETag` as an MD5.

## Verify what you downloaded

Every active file is listed with its SHA-256 hash in
[sha256sums.txt](/sha256sums.txt), in the format `sha256sum` reads:

```bash
# Linux (coreutils)
curl -fsSL https://loremfile.dev/sha256sums.txt | sha256sum -c --ignore-missing
# macOS ships no sha256sum; shasum is preinstalled
curl -fsSL https://loremfile.dev/sha256sums.txt | shasum -a 256 -c --ignore-missing
```

## Find files without a browser

[manifest.json](/manifest.json) lists every file with its size, hash, MIME type and measured
properties, and each format has its own list at `/{format}/index.json`. Keep automated
traffic under 30 requests per second per IP; in CI, download once and cache.
