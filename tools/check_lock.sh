#!/usr/bin/env bash
# Fails when tools/requirements.in changed against the merge base without
# tools/requirements.lock and tools/TOOLCHAIN_DIGEST changing too (docs/09 §4).
#
# Adding a dependency without regenerating the lock produces an image whose contents no
# longer match the recorded inputs; adding it without a new digest means CI keeps running
# the old image and the change silently does nothing.
#
# Run by ci.yml inside the toolchain container. Takes the base ref as $1, or reads
# GITHUB_BASE_REF, defaulting to origin/main.
set -euo pipefail

base="${1:-${GITHUB_BASE_REF:-main}}"
base_ref="origin/${base#origin/}"

# The job runs as root inside the toolchain image while the checkout may be owned by
# another uid; git then refuses the repository with "detected dubious ownership".
# actions/checkout does the same thing. Without this the check below cannot tell
# "no such ref" from "git will not read this repository" and would skip silently —
# which is precisely the outcome this script exists to prevent.
git config --global --add safe.directory "$(pwd)" 2>/dev/null || true

if ! git rev-parse --verify --quiet HEAD >/dev/null 2>&1; then
  echo "check_lock: git cannot read this repository, so the lock cannot be checked" >&2
  git rev-parse --verify HEAD >&2 || true
  exit 1
fi

if ! git rev-parse --verify --quiet "$base_ref" >/dev/null; then
  # A shallow clone or a fresh repository with no origin: nothing to compare against.
  echo "check_lock: $base_ref is not available, skipping (needs fetch-depth: 0)"
  exit 0
fi

merge_base="$(git merge-base HEAD "$base_ref")"
changed="$(git diff --name-only "$merge_base" HEAD -- tools/)"

changed_in() { grep -qx "$1" <<<"$changed"; }

if ! changed_in tools/requirements.in; then
  echo "check_lock: tools/requirements.in unchanged since $merge_base — nothing to check"
  exit 0
fi

missing=()
changed_in tools/requirements.lock || missing+=("tools/requirements.lock")
changed_in tools/TOOLCHAIN_DIGEST  || missing+=("tools/TOOLCHAIN_DIGEST")

if ((${#missing[@]})); then
  echo "check_lock: tools/requirements.in changed but these did not:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  cat >&2 <<'HINT'

Regenerate the lock inside the toolchain container:

  pip-compile --generate-hashes --strip-extras --allow-unsafe \
    --output-file=tools/requirements.lock tools/requirements.in

then let toolchain.yml publish a new image and record its digest in
tools/TOOLCHAIN_DIGEST. Both belong in this same pull request.
HINT
  exit 1
fi

echo "check_lock: requirements.in, requirements.lock and TOOLCHAIN_DIGEST all changed — OK"
