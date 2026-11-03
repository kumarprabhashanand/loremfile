## Can I hotlink files?

Yes. That is what the site is for.

CORS is open to every origin. Files carry `Cross-Origin-Resource-Policy: cross-origin`. Byte
ranges work. So an `<img>`, `<video>` or `fetch()` on any page can use a file directly.

## Is there a rate limit?

Yes. Keep automated traffic under 30 requests per second per IP. A faster client may be
rate-limited.

If a CI job needs many files, download them once and cache them.

## Why is there no ?download parameter?

A query string never changes a response. Every request for a path gets the same cached object,
so there is nothing for a `?download` parameter to switch on.

To save a file, use `curl -O`, `wget` or your browser's save command.

## Why do search engines not index the files?

Because we tell them not to. Files are served with `X-Robots-Tag: noindex`. Search results lead
to the format pages instead. Those pages explain what each file is and give you its URL.

## Can I mirror the files?

Yes. Every file is CC0 1.0, so you can copy it for any purpose without asking.

Check your copy against [sha256sums.txt](/sha256sums.txt). And please download once rather than
over and over.

## Will a file ever change?

No. The bytes at a published path never change. If a file turns out to be defective, we publish
a replacement at a new path, and the old entry points to it.

In rare cases a file can be withdrawn. The [terms of use](/legal/terms) cover that.

## Where do the files come from?

We generate every file with the open-source tooling in the
[repository](https://github.com/kumarprabhashanand/loremfile). It runs inside a pinned
container and starts from synthetic data.

No file contains third-party media or real personal data. The one exception is that some images
and PDFs rasterise glyphs from open-licensed fonts. THIRD_PARTY.md in the repository lists
them.
