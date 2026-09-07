# Contributing

Thanks for helping. This project has one rule that outranks everything else:

> **A published URL never changes.** The bytes, `sha256`, byte count and MIME type at a
> path are frozen the moment they are deployed. A fix is a **new path**; the old entry
> gets `supersededBy`. CI and the R2 bucket lock rules both enforce this — a pull request
> that modifies an existing `manifest.json` entry cannot merge.

## Licensing of contributions

By opening a pull request you agree that your generator code is licensed **MIT** and that
any fixtures it produces are dedicated to the public domain under **CC0 1.0**. There is no
CLA to sign (`docs/13-legal-and-policy.md` §10).

## Requesting a fixture

Open a [fixture request](../../issues/new?template=fixture-request.yml). Good requests say
what you are testing, not just what file you want — "a 10 MB PDF and a 10 MB + 1 byte PDF
so I can test my upload limit" tells us the boundary matters, and we will add both.

## The naming grammar

```
https://loremfile.dev/{format}/{name}
```

- `format` is `^[a-z0-9]+$` — the first path segment, e.g. `pdf`, `mp4`, `bin`, `edge`.
- `name` is `^[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+)+$` — lowercase kebab-case, then one or
  more extensions: `a4-3pages.pdf`, `3-text-files.tar.gz`, `people-1000.parquet`.
- No uppercase, no spaces, no underscores.
- Descriptors are ordered tokens: `[variant]-[dimension|duration|count|size]-[qualifiers]`,
  e.g. `640x480`, `5s`, `3pages`, `100k-rows`, `10mib-plus-1`, `utf16le`, `h264-baseline`.
- **Sizes are units-explicit**: `kb`/`mb`/`gb` are decimal (1 MB = 1,000,000 bytes),
  `kib`/`mib`/`gib` are binary. The validators enforce this.
- HLS is the single nested exception: `hls/{variant}/(index|master).m3u8` and
  `hls/{variant}/seg-[0-9]{3}.ts`.

The full grammar is `docs/03-http-contract.md` §1; the catalog of every fixture and its
parameters is `docs/05-fixture-catalog.md`.

## What we will not accept

`docs/13-legal-and-policy.md` §5 is the binding list. In short: no malware test strings or
exploit proofs-of-concept, no executables or macros, no decompression bombs, no
script-bearing PDFs or SVGs, nothing that looks like a credential (including test card
numbers and private keys), nothing identifying a real person, no third-party copyrighted
content, nothing illegal or sexual or violent or hateful or political, and nothing over
100 MB. Fixtures are boring by design. `validators/policy.py` scans for most of this and
the rest is caught in review.

## Making a change

Everything below runs **inside the pinned toolchain image**. Only its output is
authoritative — a host `ffmpeg` or Pillow produces different bytes and the lock check will
tell you so.

```bash
docker pull "$(cat tools/TOOLCHAIN_DIGEST)"
docker run --rm -it -v "$PWD:/work" "$(cat tools/TOOLCHAIN_DIGEST)" bash
pip install -e .

loremfile catalog validate
loremfile build    --only pdf/a4-3pages.pdf
loremfile validate --only pdf/a4-3pages.pdf
loremfile manifest update      # then commit manifest.json and sha256sums.txt
```

**Never hand-edit `manifest.json` or `sha256sums.txt`.** Run `loremfile manifest update`
and commit what it writes. CI regenerates your fixture from the catalog and compares; if
your committed entry differs, the job summary prints the exact entries to commit.

Adding a **new format** also needs a bucket-lock rule: run `loremfile infra locks --write`
and say so in the pull request description — the owner applies it once before the deploy.

### Every generator ships complete

A generator family is not mergeable on its own. The same pull request must contain:

1. the generator,
2. its validator,
3. a **negative test** (a corrupted input must fail the validator),
4. a **determinism test** that runs the generator twice and asserts identical bytes,
5. the catalog entries, with `description`, `tags`, `expect` and `size_class`,
6. the regenerated `manifest.json` and `sha256sums.txt`,
7. a `CHANGELOG.md` line listing every added path.

### Adding a dependency

Add it to `tools/requirements.in`, regenerate `tools/requirements.lock`
(`pip-compile --generate-hashes`) **and** bump `tools/TOOLCHAIN_DIGEST` — all in the same
pull request. `tools/check_lock.sh` fails the build otherwise.

## Code style

Python 3.12, type hints everywhere, `ruff` for lint and format, `mypy --strict` on `src/`.
Generators are pure functions of `(ctx, params)` with no global state, and their docstrings
state the exact output properties they guarantee.

## Where to start

Issues labelled **`good first fixture`** are small, self-contained and have their
parameters already decided in `docs/05-fixture-catalog.md`.
