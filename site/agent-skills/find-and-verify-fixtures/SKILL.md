---
name: find-and-verify-fixtures
description: Find a sample file on loremfile.dev by format, download it, and verify its bytes against the SHA-256 in the manifest. Use when a test or tool needs a real file of a given format whose exact bytes are known.
---

# Find, fetch and verify a loremfile.dev fixture

Every file on loremfile.dev is CC0 and immutable: its bytes never change at a published
path, and the manifest records each file's size and SHA-256.

## Find one

- **One format:** `GET https://loremfile.dev/{format}/index.json`, for example
  `https://loremfile.dev/pdf/index.json`. Its `fixtures` array lists that format's files.
- **Every format:** `GET https://loremfile.dev/manifest.json`. `formats` names each format
  and `fixtures` lists every file.
- Pick an entry by `description`, `tags`, `bytes` or `props`. Each entry carries `url`,
  `bytes`, `mime` and `sha256`.

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
