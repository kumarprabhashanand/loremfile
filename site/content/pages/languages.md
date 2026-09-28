Every fixture is a plain file over HTTPS, so fetching one needs no library and no client:
a `GET`, a SHA-256, and a comparison. Below is the same task in five languages — download
`pdf/minimal.pdf` and check it against the hash this service publishes — using each
language's standard library and nothing else. Every one of these runs in CI on each
change, against this site, so what you are reading is what was last executed rather than
what once worked.

**Two files carry the hashes, and both are canonical.**
[`manifest.json`](/manifest.json) is the full record — path, bytes, MIME type, tags and
measured properties as well as `sha256` — and it is what to read when you want to choose
files or check anything besides the hash. [`sha256sums.txt`](/sha256sums.txt) is the same
hashes in the format `sha256sum -c` reads, one line per file, which a two-line shell
script or a language without a bundled JSON parser can consume directly. The snippets use
whichever suits the language: Python, JavaScript and Go parse the manifest; shell and Java
read the sums file.

## Shell

<!-- include: examples/verify.sh -->

## Python

<!-- include: examples/verify.py -->

## JavaScript

<!-- include: examples/verify.mjs -->

## Go

<!-- include: examples/verify.go -->

## Java

<!-- include: examples/Verify.java -->

## Any other language

Nothing above is special to these five. The contract is small enough to implement
anywhere: a plain `GET` over HTTPS returns the bytes; CORS is open, so a browser may fetch
any fixture from any origin; `Range` requests are supported, so you can take the first
kilobyte of a 100 MB file; and every published hash is in `manifest.json` and
`sha256sums.txt`. Paths never change meaning — the bytes at a URL are fixed forever, and a
correction is published at a new path — so a hash you record today keeps matching.

Please stay under 30 requests a second, and prefer one request per file over retrying in a
loop. If you would rather not write any of this, the [GitHub Action](/docs/getting-started)
and the `loremfile` command-line client do it for you, with the same verification.
