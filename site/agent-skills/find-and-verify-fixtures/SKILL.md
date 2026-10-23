---
name: find-and-verify-fixtures
description: Find a sample file on loremfile.dev by format or by the failure it should cause, download it, and verify its bytes against the SHA-256 in the manifest. Use when a test or tool needs a real file of a given format, or a deliberately broken one, whose exact bytes are known.
---

# Find, fetch and verify a loremfile.dev fixture

Every file on loremfile.dev is CC0 and immutable: its bytes never change at a published
path, and the manifest records each file's size and SHA-256.

## Find one

- **One format:** `GET /{format}/index.json` on the site, for example
  `https://loremfile.dev/pdf/index.json`. Its `fixtures` array lists that format's files.
- **Every format:** `GET https://loremfile.dev/manifest.json`. `formats` names each format
  and `fixtures` lists every file.
- **In prose:** `https://loremfile.dev/llms.txt` says what the service is and how to use it;
  `https://loremfile.dev/llms-full.txt` adds every file in one table.
- **A page as Markdown:** append `/index.md` to any format or testing-guide page, for example
  `https://loremfile.dev/pdf/index.md`: the page's text, with each file's path, size, media
  type and measured properties in tables.
- **Discovery:** `https://loremfile.dev/.well-known/api-catalog` (RFC 9727) links
  `manifest.json`, `sha256sums.txt` and every `{format}/index.json` to their schema and docs.
- Pick an entry by `description`, `tags`, `bytes` or `props`. Each entry carries `url`,
  `bytes`, `mime` and `sha256`.

## A file for a failure case

The `edge` format holds deliberately broken files: `https://loremfile.dev/edge/index.json`.
Each entry's `props` say what is wrong with it and what a reader should do:

- `defect` names the kind of damage and `damage` describes it in words.
- `intended_format` is the format the file claims to be, and `compare_with` is a healthy
  file of that format to test alongside it.
- `outcome` is `must-fail` (every conforming reader must refuse it), `may-recover` (part of
  it can still be read, and a reader that does is not wrong) or `varies` (readers disagree,
  and neither outcome is guaranteed).

`https://loremfile.dev/testing/parsers` sorts these files by outcome and says why each one
fails; `https://loremfile.dev/testing/uploads` covers size limits, mislabelled types and
hostile archives.

## Fetch it

`GET` the entry's `url`. If only the size matters, `HEAD` answers with a `Content-Length`
equal to `bytes`. Query strings are ignored. Keep below 30 requests per second, and download
once and cache rather than fetching the same file in a loop.

## Verify it

Compute the SHA-256 of the downloaded bytes and compare it with the entry's `sha256`.
Reject the file on any difference.

```sh
curl -fsSL --create-dirs -o pdf/a4-3pages.pdf https://loremfile.dev/pdf/a4-3pages.pdf
curl -fsSL https://loremfile.dev/sha256sums.txt | grep ' pdf/a4-3pages.pdf$' | sha256sum -c
```

macOS has no `sha256sum`; use `shasum -a 256 -c` instead.

```python
import hashlib
import json
import urllib.request

index = json.load(urllib.request.urlopen("https://loremfile.dev/pdf/index.json"))
entry = min(index["fixtures"], key=lambda e: e["bytes"])
data = urllib.request.urlopen(entry["url"]).read()
assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]
```

A page alone is also enough: the JSON-LD `Dataset` on every format and testing-guide page
lists each file's `contentUrl`, `contentSize` and `sha256`.

## From an agent: the MCP server

`npx -y loremfile mcp` (Node) or `uvx loremfile mcp` (Python) runs a Model Context Protocol
server over stdio with three read-only tools: `list_fixtures` (filter by `format`, `tag` or
`max_bytes`), `describe_fixture` (one entry, with its `sha256` and `props`) and `verify_file`
(hash a local file against the manifest: `ok`, `changed` or `missing`). Client configuration:
`https://loremfile.dev/docs/mcp`.
