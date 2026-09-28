# loremfile

Download [loremfile.dev](https://loremfile.dev) sample files and check every byte against
the published manifest.

```console
$ pip install loremfile
$ loremfile get pdf/minimal.pdf mp4/720p-5s.mp4
  written  mp4/720p-5s.mp4  1,974,574 bytes
  written  pdf/minimal.pdf  317 bytes
files=2, dest=loremfile-fixtures
```

Everything it does can be done with `curl` and `sha256sum -c`. What it adds is doing it
correctly by default: every file is verified, and a file that fails is not written.

## Commands

| Command | |
|---|---|
| `loremfile get PATH…` | Download those fixtures into `--dest` (default `loremfile-fixtures`), verifying each. |
| `loremfile get --format svg --format pdf` | The same for every published file of a format. |
| `loremfile list [--format F] [--tag T] [--max-bytes N]` | What is published, without downloading. |
| `loremfile verify [PATH…]` | Check files already on disk against the manifest. |

Every command takes `--json` for scripts, `--quiet`, and `--catalog-version X.Y.Z` to
refuse to run if loremfile.dev has moved on. `get` also takes `--force` (overwrite) and
`--dry-run` (what it would fetch, and how many bytes).

Exit codes: `0` fine, `1` a file failed verification or is missing, `2` the request was
wrong, `3` loremfile.dev could not be read.

## What it will not do

- **Write a file it could not verify.** There is no `--no-verify`.
- **Talk to any host but loremfile.dev.** No mirror option, and redirects off the host are
  not followed.
- **Take credentials.** Nothing it does needs authentication, so it accepts none.
- **Exceed the published rate limit**: one file at a time, a pause between them, and a
  429 is waited out rather than retried tightly.
- **Generate fixtures.** Those are built in a pinned toolchain image; a client that made
  its own would produce different bytes and undermine the only promise the project makes.

## Python versions

3.11, 3.12, 3.13 and 3.14, tested in CI on Linux, macOS and Windows. The floor is the
oldest CPython still receiving security fixes when a release is cut; a new one is
supported within six weeks of its release, and an end-of-life one is dropped in the next
minor release.

Zero dependencies — standard library only.

## In GitHub Actions, prefer the action

```yaml
- uses: kumarprabhashanand/loremfile/action@action-v1
  with:
    paths: pdf/minimal.pdf mp4/720p-5s.mp4
```

It is shell only and needs no install step. This client is for everywhere else: a laptop,
a Makefile, a CI system that is not Actions, or Windows — which the action does not
support because it needs `sha256sum`.

## One name, two tools

The console script installed here is `loremfile`, which is also the name of the
repository's own development CLI (the one that generates and publishes the fixtures).
They are never installed together — that tool lives only inside the project's toolchain
image — but a contributor who installs both into one environment gets whichever was
installed last. The published package contains the client only: no generators, no
validators, no uploader, no infrastructure code.

## Licence

MIT for the client; the files it downloads are CC0.
