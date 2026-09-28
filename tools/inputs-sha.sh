#!/usr/bin/env bash
# The hash of everything that goes *into* the toolchain image (docs/09 §4).
#
# An image build is not reproducible: rebuilding identical inputs produces a different
# digest, and toolchain.yml used to read that as "the image changed" and open a digest
# bump pull request after every unrelated change to tools/. This hash is what actually
# changed or did not. It is baked into the image as a label, so the question can be asked
# of a published image rather than of the branch it came from.
#
# tools/smoke.sh is deliberately absent: it is mounted at test time, never copied in, so
# editing it changes no image.
set -euo pipefail

root="${1:-$(cd "$(dirname "$0")/.." && pwd)}"

if command -v sha256sum >/dev/null 2>&1; then
  digest() { sha256sum; }
elif command -v shasum >/dev/null 2>&1; then
  digest() { shasum -a 256; }
else
  echo "neither sha256sum nor shasum is available" >&2
  exit 1
fi

cat "$root/tools/Dockerfile" "$root/tools/apt-versions.txt" "$root/tools/requirements.lock" \
  | digest | cut -d' ' -f1
