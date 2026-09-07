#!/usr/bin/env bash
# Smoke test for the pinned toolchain image (docs/06 §9).
#
#   docker build -f tools/Dockerfile -t loremfile-toolchain:local .
#   docker run --rm -v "$PWD/tools:/t:ro" loremfile-toolchain:local bash /t/smoke.sh
#
# Run by toolchain.yml on every image build (M1.3) and by hand after any change to
# tools/Dockerfile, tools/apt-versions.txt or tools/requirements.lock. It fails on the
# first problem, so a green run means every check below passed.
set -euo pipefail

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

echo "== apt versions match tools/apt-versions.txt =="
while IFS='=' read -r pkg want; do
  case "$pkg" in ''|\#*) continue ;; esac
  got="$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null || true)"
  [ "$got" = "$want" ] || fail "$pkg is '$got', tools/apt-versions.txt says '$want'"
  printf '  ok  %s=%s\n' "$pkg" "$got"
done < <(sed 's/[[:space:]]*#.*//' /t/apt-versions.txt | grep '=')

echo "== ffmpeg encoders =="
encoders="$(ffmpeg -hide_banner -encoders 2>/dev/null | awk '{print $2}')"
# P1 codecs, then the P2 ones (libx265/libsvtav1) confirmed present in M1.2.
for e in libx264 libvpx libvpx-vp9 libopus libvorbis libmp3lame aac flac libtheora \
         prores_ks libx265 libsvtav1; do
  grep -qx "$e" <<<"$encoders" || fail "ffmpeg encoder '$e' is missing"
  printf '  ok  %s\n' "$e"
done

echo "== SQLite FTS5 =="
sqlite3 :memory: 'PRAGMA compile_options;' | grep -qx ENABLE_FTS5 \
  || fail 'SQLite was built without ENABLE_FTS5'
rows="$(sqlite3 :memory: "CREATE VIRTUAL TABLE t USING fts5(body);
  INSERT INTO t VALUES('lorem ipsum dolor');
  SELECT count(*) FROM t WHERE t MATCH 'lorem';")"
[ "$rows" = "1" ] || fail "fts5 MATCH returned $rows rows, expected 1"
echo '  ok  ENABLE_FTS5 and a MATCH query'

echo "== other binaries =="
qpdf --version >/dev/null   || fail 'qpdf missing'
avifenc --version >/dev/null || fail 'avifenc (libavif-bin) missing'
git --version >/dev/null    || fail 'git missing'
gh --version >/dev/null     || fail 'gh missing'
echo '  ok  qpdf avifenc git gh'

echo "== python imports and zstd =="
python - <<'PY'
import sys, tarfile, importlib
mods = ["zstandard", "fpdf", "pypdf", "PIL", "docx", "openpyxl", "pptx", "pyarrow",
        "fastavro", "py7zr", "pyzipper", "fontTools", "brotli", "mutagen", "lxml",
        "yaml", "tomli_w", "jsonschema", "pydantic", "click", "jinja2", "boto3",
        "requests", "icalendar", "vobject", "cryptography", "markdown_it", "ijson",
        "html5lib", "pytest", "responses"]
bad = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as exc:
        bad.append(f"{m}: {type(exc).__name__}: {exc}")
if bad:
    sys.exit("SMOKE FAIL: imports failed:\n  " + "\n  ".join(bad))
print(f"  ok  {len(mods)} modules import")

# .tar.zst goes through the zstandard package: this Python has no zstd tarfile mode.
try:
    tarfile.open("/tmp/smoke.tar.zst", "w:zst")
except tarfile.CompressionError:
    print("  ok  tarfile has no zstd mode, as expected (use zstandard)")
else:
    sys.exit("SMOKE FAIL: tarfile grew a zstd mode — revisit the .tar.zst generator")

import zstandard
payload = b"lorem" * 1000
if zstandard.ZstdDecompressor().decompress(
        zstandard.ZstdCompressor().compress(payload)) != payload:
    sys.exit("SMOKE FAIL: zstandard round trip mismatch")
print("  ok  zstandard round trip")
PY

echo "== determinism environment =="
[ "${TZ:-}" = "UTC" ]                        || fail "TZ is '${TZ:-}', expected UTC"
[ "${PYTHONHASHSEED:-}" = "0" ]              || fail "PYTHONHASHSEED is '${PYTHONHASHSEED:-}', expected 0"
[ "${SOURCE_DATE_EPOCH:-}" = "1577836800" ]  || fail "SOURCE_DATE_EPOCH is '${SOURCE_DATE_EPOCH:-}', expected 1577836800"
[ "${LANG:-}" = "C.UTF-8" ]                  || fail "LANG is '${LANG:-}', expected C.UTF-8"
echo "  ok  TZ=$TZ LANG=$LANG PYTHONHASHSEED=$PYTHONHASHSEED SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH"

echo
echo "ALL SMOKE CHECKS PASSED"
