#!/usr/bin/env python3
"""Fetch one fixture and check it against the hash in the manifest. Standard library."""

import hashlib
import json
import sys
import urllib.request

BASE, WANTED = "https://loremfile.dev/", "pdf/minimal.pdf"

with urllib.request.urlopen(BASE + "manifest.json") as response:
    manifest = json.load(response)
entry = next(f for f in manifest["fixtures"] if f["path"] == WANTED)

with urllib.request.urlopen(BASE + WANTED) as response:
    body = response.read()

digest = hashlib.sha256(body).hexdigest()
if digest != entry["sha256"]:
    sys.exit(f"{WANTED}: got {digest}, the manifest says {entry['sha256']}")
print(f"{WANTED}: {len(body)} bytes, sha256 matches")
