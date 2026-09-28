#!/usr/bin/env bash
# Is the dependency lock the faithful resolution of tools/requirements.in (docs/09 §4)?
#
# The question used to be asked of the diff — "requirements.in changed, so the lock and
# the digest must have changed too" — and that gets the common case backwards: a floor
# raised to a version the lock already pins is a legitimate no-op, and the rule turned it
# into a failure nobody could fix honestly (old PR #30). check_lock.py now asks the
# artifacts instead: regenerating must reproduce the lock byte for byte, and every
# constraint must be satisfied by what is pinned.
#
# This script keeps the one question that is genuinely about the diff: a change to the
# lock has to come with a new image, or CI keeps running an image whose contents no
# longer match the recorded inputs.
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

# A lock that changed without a new image means CI keeps running the old contents. This
# one *is* about the diff: no artifact can tell you which image a workflow will pull.
if changed_in tools/requirements.lock && ! changed_in tools/TOOLCHAIN_DIGEST; then
  echo "check_lock: tools/requirements.lock changed but tools/TOOLCHAIN_DIGEST did not." >&2
  cat >&2 <<'HINT'

Let toolchain.yml publish an image from the new lock and record its digest:

  gh workflow run toolchain.yml --ref <this branch>

then copy the digest from the run summary into tools/TOOLCHAIN_DIGEST, in this same
pull request. Without it every job keeps pulling the image built from the old lock.
HINT
  exit 1
fi

# Everything else is a question about the files themselves, so it is asked on every run
# rather than only when the diff touches them.
python3 "$(dirname "$0")/check_lock.py" "$(pwd)"
