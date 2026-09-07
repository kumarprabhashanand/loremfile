# loremfile

**Free, CC0, hotlink-friendly sample files for every file type.** Lorem Picsum, but for
PDFs, images, audio, video, office documents, data files, archives, fonts, text encodings,
raw byte blobs and deliberately malformed edge cases.

```
https://loremfile.dev/pdf/a4-3pages.pdf
https://loremfile.dev/bin/10mb.bin
https://loremfile.dev/mp4/720p-5s.mp4
https://loremfile.dev/edge/truncated.png
```

No ads, no accounts, no rate-limit surprises, no attribution required. Open CORS, byte-range
support, one-year immutable caching, and a machine-readable
[`manifest.json`](https://loremfile.dev/manifest.json) with SHA-256 hashes for every file.

> **Status: not launched yet.** The specification is complete and lives in [`docs/`](docs/).
> Implementation is in progress; `loremfile.dev` does not serve content yet. Follow the
> [Implementation status](../../issues) issue for progress.

## Canonical host

The canonical host is **`https://loremfile.dev`**.

This README is the out-of-band pointer: if `loremfile.dev` is ever unavailable or moves, the
current canonical host is stated here first. Do not rely on any other mirror.

## Promises

- **Immutability.** A published URL keeps the exact same bytes forever. Hash, byte count and
  MIME type never change at a path. A fix is a new path; the old entry records `supersededBy`.
  Files are removed only for legal reasons, and the manifest keeps a tombstone.
- **Hotlinking is welcome.** That is what this is for. Please keep automated traffic under
  30 requests per second per client (the edge rate-limits at 300 requests / 10 s per IP).
- **No tracking.** No cookies, no analytics scripts, no accounts.

## For agents and CI

- [`/llms.txt`](https://loremfile.dev/llms.txt) — what this service is, in one file.
- [`/manifest.json`](https://loremfile.dev/manifest.json) — every fixture with path, bytes,
  `sha256`, MIME type, tags and format-specific properties.
- [`/sha256sums.txt`](https://loremfile.dev/sha256sums.txt) — verify downloads with
  `sha256sum -c`.
- `/{format}/index.json` — one format at a time.

## Licences

| What | Licence |
|---|---|
| Every file served under a format path (`/pdf/…`, `/bin/…`, `/edge/…`) | [CC0 1.0 Universal](LICENSES/CC0-1.0.txt) — public domain, no attribution needed |
| Generators, site and tooling in this repository | [MIT](LICENSE) |
| Website text and graphics | CC BY 4.0, attribute "loremfile.dev" |

Third-party tools used to generate the files are listed in [`THIRD_PARTY.md`](THIRD_PARTY.md).
No third-party media is redistributed — everything is generated.

## Repository

| Path | What |
|---|---|
| [`docs/`](docs/) | The full specification, 00–19. Start with [`docs/README.md`](docs/README.md). |
| [`review/`](review/) | The three independent review passes the specification went through. |
| `catalog/` | Declarative fixture definitions, one YAML per format. |
| `src/loremfile/` | Generators, validators, site builder, uploader, infrastructure code. |
| `infra/` | Cloudflare desired state, applied by workflow. |
| `manifest.json` | Generated lock file — never hand-edited. |

## Contributing

Fixture requests and bug reports go in [Issues](../../issues); see
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the naming grammar and what makes a good fixture.
Security reports: [`SECURITY.md`](SECURITY.md).

By opening a pull request you agree that generator code is MIT and any resulting fixtures
are CC0.
