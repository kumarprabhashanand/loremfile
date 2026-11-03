You want to fetch a file in your own language and check you got the right bytes. You do not need
a library for that. Every fixture is a plain file over HTTPS, so it takes a `GET`, a SHA-256 and
a comparison.

Below is the same job in five languages: download `pdf/minimal.pdf` and check it against the
hash we publish. Each one uses the language's standard library and nothing else.

Every one of these runs in CI on each change, against this site. What you are reading is what
was last executed.

## Where do the hashes come from?

Two files carry them, and both are canonical.

[`manifest.json`](/manifest.json) is the full record: path, bytes, MIME type, tags, measured
properties and `sha256`. Read it when you want to choose files, or check anything besides the
hash.

[`sha256sums.txt`](/sha256sums.txt) holds the same hashes in the format `sha256sum -c` reads,
one line per file. A two-line shell script can use it. So can a language with no bundled JSON
parser.

The snippets use whichever suits the language. Python, JavaScript and Go parse the manifest.
Shell and Java read the sums file.

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

## What if my language is not here?

Nothing above is special to these five. The contract is small enough to implement anywhere:

- A plain `GET` over HTTPS returns the bytes.
- CORS is open, so a browser can fetch any fixture from any origin.
- `Range` requests work, so you can take the first kilobyte of `mp4/50mb.mp4`.
- Every published hash is in `manifest.json` and `sha256sums.txt`.

Paths never change meaning. The bytes at a URL are fixed forever, and a correction is published
at a new path. So a hash you record today keeps matching.

Please stay under 30 requests a second. Fetch each file once rather than retrying in a loop.

If you would rather not write any of this, the [GitHub Action](/docs/getting-started) and the
`loremfile` command-line client do it for you. They verify each hash the same way.
