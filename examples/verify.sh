#!/usr/bin/env sh
# Fetch one fixture and check it against the published hash. POSIX sh and curl.
# macOS ships `shasum` where Linux ships `sha256sum`; both read this format.
set -eu
check=$(command -v sha256sum || echo "shasum -a 256")

curl -fsS --create-dirs -o pdf/minimal.pdf https://loremfile.dev/pdf/minimal.pdf
curl -fsS https://loremfile.dev/sha256sums.txt | grep ' pdf/minimal\.pdf$' | $check -c -
