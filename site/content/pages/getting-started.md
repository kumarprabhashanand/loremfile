## How do the URLs work?

Every file lives at `https://loremfile.dev/{format}/{name}`. The format is the first part of the
path. The name tells you what is inside.

`pdf/a4-3pages.pdf` is three A4 pages. `csv/people-1000.csv` is a thousand rows of synthetic
people.

There is nothing to sign up for and no key to send. [Naming and sizes](/docs/naming) explains
how the names are built.

## Can I use a file straight from a web page?

Yes. A page on any origin can fetch a file. CORS allows `GET` and `HEAD` from every origin.
Byte-range requests work too, so a media player can seek.

Query strings are ignored. Adding `?v=2` does not bust a cache, and it does not change what you
receive.

If you would rather keep a copy:

```bash
curl -O https://loremfile.dev/pdf/a4-3pages.pdf
```

## How do I use it in a GitHub workflow?

Add the action to a step and list the files you want:

```yaml
- uses: kumarprabhashanand/loremfile/action@action-v1
  with:
    paths: pdf/minimal.pdf mp4/720p-5s.mp4
```

The files land in `loremfile-fixtures/`. Each one is checked against its hash in the manifest.

To get every file of a format, add `formats: pdf` beside `paths` or in place of it.

The action runs on Linux and macOS runners. It downloads one file at a time and backs off if it
is rate limited.

## How do I use it from the command line?

The same small client is published for Python and for Node. Both have `get`, `list` and
`verify`, with the same flags and the same exit codes.

**Neither has a dependency.** The Python package declares `dependencies = []` and uses only the
standard library. The npm package's `package.json` lists no dependencies and uses only Node's
built-ins. Installing either one installs that one package.

```bash
# Python 3.11 or newer
pip install loremfile
loremfile get pdf/minimal.pdf
loremfile get --format pdf

# Node 20 or newer, no install step
npx loremfile get pdf/minimal.pdf
npx loremfile get --format pdf
```

Each file is checked against its hash in the manifest before it is written. A file that does
not match is not written at all.

The exit codes are:

- `0`: everything is fine
- `1`: a file failed verification or is missing
- `2`: the request was wrong
- `3`: loremfile.dev could not be read

Both clients install a command named `loremfile`. On a machine with both, whichever comes first
on `PATH` runs.

## How do I use it in a pytest suite?

Some files are too big to commit: multi-megabyte video, audio and archives. For those, the
Python client gives pytest a `loremfile` fixture. `pip install loremfile` is the whole setup.

```python
def test_reads_a_real_mp4(loremfile):
    video = loremfile("mp4/10mb.mp4")  # a pathlib.Path, checked against the manifest
```

The first call downloads the file into `.pytest_cache` and checks its SHA-256. A file that does
not match is never returned.

Published files never change at their path. So after the first call, the suite needs no network
for that file. In CI, cache `.pytest_cache/d/loremfile` between runs.

If your tests may not touch the network, or the file you need is a 4 KB PDF, commit the file
instead.

## How big is a file before I download it?

```bash
curl -sI https://loremfile.dev/mp4/720p-5s.mp4 | grep -i content-length
```

`Content-Length` equals the `bytes` field in the manifest. Do not treat the `ETag` as an MD5.

## How do I check what I downloaded?

[sha256sums.txt](/sha256sums.txt) lists every active file with its SHA-256 hash. It uses the
format that `sha256sum` reads:

```bash
# Linux (coreutils)
curl -fsSL https://loremfile.dev/sha256sums.txt | sha256sum -c --ignore-missing
# macOS ships no sha256sum; shasum is preinstalled
curl -fsSL https://loremfile.dev/sha256sums.txt | shasum -a 256 -c --ignore-missing
```

## What if I use another language?

[Use it from your language](/docs/languages) has the same fetch-and-verify in shell, Python,
JavaScript, Go and Java. Each one is a complete program. The page also states the contract, so
you can write the same thing in any language that is not on that list.

## How do I find a file without a browser?

[manifest.json](/manifest.json) lists every file with its size, hash, MIME type and measured
properties. Each format also has its own list at `/{format}/index.json`.

Keep automated traffic under 30 requests per second per IP. The action above paces its
downloads for you.
