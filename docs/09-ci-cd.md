# 09 — CI/CD and Repository Setup

## 1. Repository settings (GitHub, one-time)

| Setting | Value |
|---|---|
| Visibility | Public (Actions minutes are free on standard runners for public repositories) |
| Default branch | `main`; a second, unprotected branch `ops-log` holds only `ops-log.md`, written by `health.yml` (created once in M4.4 as an orphan branch) |
| Ruleset on `main` | Require pull request before merging (0 required approvals — single maintainer, but PRs give an audit trail; CODEOWNERS is therefore informational until a second maintainer exists); require status checks — the names GitHub lists are the **job names** `lint-and-test` (added in M1.5) and `build-and-validate` (added to the ruleset in M3.1, the first PR that contains the job, otherwise a never-reporting required check would block every PR); require linear history; block force pushes; block deletions; require conversation resolution |
| Environment `production` | Deployment branch rule: only `main`; secrets: `CLOUDFLARE_API_TOKEN`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `CLOUDFLARE_ANALYTICS_TOKEN` |
| Repository variables (not environment-scoped, readable by every workflow) | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_ZONE_ID`, `R2_BUCKET=loremfile-public`, `SITE_HOST=loremfile.dev` |
| Actions permissions | Allow actions from GitHub and verified creators only (`actions/*`, `docker/*` qualify; no third-party actions are used — the digest-bump PR is opened with `gh`); default `GITHUB_TOKEN` permissions: read-only |
| Fork PR workflows | Default (no secrets for fork PRs; `pull_request_target` is never used) |
| Security | Private vulnerability reporting: on; Dependabot alerts + security updates: on; secret scanning + push protection: on |
| Packages | GHCR package `loremfile-toolchain` public, linked to the repo |
| Labels | `health`, `cost`, `rotation-due`, `determinism`, `infra-drift`, `fixture-request`, `security`, `good first fixture` |

## 2. Secrets and variables

| Name | Kind | Scope | Source | Rotation |
|---|---|---|---|---|
| `CLOUDFLARE_API_TOKEN` | secret | env `production` | T1 (`08` §2.9) | 180 days |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | secrets | env `production` | T2 | 180 days |
| `CLOUDFLARE_ANALYTICS_TOKEN` | secret | env `production` | T4 (read-only) | 365 days |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_ZONE_ID`, `R2_BUCKET`, `SITE_HOST` | variables | repository | Cloudflare dashboard (Overview page of the zone) | n/a |
| `GITHUB_TOKEN` | automatic | per job | GitHub | n/a; permissions declared per job |

PR builds never receive the `production` environment, so they cannot upload or change infrastructure.

## 3. Workflows

All actions are pinned to full commit SHAs (Dependabot keeps them current), resolved with `gh api repos/<action-owner>/<action-repo>/commits/<tag> --jq .sha`; the version tag stays in a trailing comment.

**Resolved 2026-09-07.** The major versions this document originally assumed (`checkout` v4, `login-action` v3, `build-push-action` v6, artifacts v4) were all out of date by the time the first workflow was written; the table below is what the registries actually served on that date.

| Action | Version | Commit SHA | Used by |
|---|---|---|---|
| `actions/checkout` | `v7.0.1` | `3d3c42e5aac5ba805825da76410c181273ba90b1` | all workflows |
| `actions/upload-artifact` | `v7.0.1` | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` | `ci.yml`, `toolchain.yml` |
| `actions/download-artifact` | `v8.0.1` | `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c` | `ci.yml` |
| `docker/login-action` | `v4.6.0` | `dbcb813823bdd20940b903addbd779551569679f` | `toolchain.yml` |
| `docker/build-push-action` | `v7.3.0` | `53b7df96c91f9c12dcc8a07bcb9ccacbed38856a` | `toolchain.yml` |

`upload-artifact` v7 and `download-artifact` v8 are the current majors of each; confirm they interoperate when `ci.yml` first passes an artifact between jobs (M1.5).

Chicken-and-egg note: `ci.yml` references the toolchain image by digest, so `toolchain.yml` must run once (M1.3) **before** `ci.yml` is enabled (M1.5).

### 3.1 `ci.yml` — every pull request (not on push to `main`: `deploy.yml` re-runs the same generate/validate/check steps on the merged commit, so a second CI run would only duplicate compute)

```yaml
name: ci
on:
  pull_request:
  workflow_dispatch:
concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }
permissions: { contents: read }
jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    container: { image: "ghcr.io/<OWNER>/loremfile-toolchain@sha256:<DIGEST>" }
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@<SHA-v4>            # v4
        with: { fetch-depth: 0 }                   # merge-base manifest and lock-file checks need history
      - run: pip install -e . --no-deps
      - run: ruff check . && ruff format --check .
      - run: mypy src/
      - run: tools/check_lock.sh                   # fails if tools/requirements.in changed vs merge-base without requirements.lock and TOOLCHAIN_DIGEST changing too
      - run: loremfile catalog validate
      - run: pytest -q tests/unit
  build-and-validate:
    runs-on: ubuntu-latest
    container: { image: "ghcr.io/<OWNER>/loremfile-toolchain@sha256:<DIGEST>" }
    timeout-minutes: 45
    needs: lint-and-test
    steps:
      - uses: actions/checkout@<SHA-v4>
        with: { fetch-depth: 0 }
      - run: pip install -e . --no-deps
      - run: loremfile build --new -j 4                # fixtures absent from origin/main:manifest.json (+ unpublished dependencies)
      - run: loremfile validate
      - run: pytest -q tests/integration               # policy scan + size totals over build/fixtures
      - run: loremfile manifest check                  # lock rule on published entries; committed entries for new fixtures must equal regenerated hashes/props
      - run: loremfile site build
      - run: pytest -q tests/site
      - name: Summarise
        run: loremfile manifest check --json > summary.json && python -m loremfile.ci_summary summary.json >> "$GITHUB_STEP_SUMMARY"
      - uses: actions/upload-artifact@<SHA-v4>
        with: { name: site-preview, path: build/site, retention-days: 7 }
      - uses: actions/upload-artifact@<SHA-v4>
        if: github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name == github.repository   # not for fork PRs (storage abuse)
        with: { name: new-fixtures, path: build/fixtures, retention-days: 7 }
      - name: Manifest diff for the author
        if: failure()
        run: loremfile manifest check --json | python -m loremfile.ci_summary --explain >> "$GITHUB_STEP_SUMMARY"   # prints the exact entries to commit when a committed entry does not match
```

**How this file is built up (M1.5 onwards).** The listing above is the finished workflow. Each step is added by the milestone that creates the thing it checks, so the job never calls a command that does not exist yet: **M1.5** lands `lint-and-test` with checkout, `pip install -e .`, ruff, `mypy src/` and `pytest tests/unit`; **M1.6** adds `tools/check_lock.sh` and `loremfile catalog validate` to the same job; **M3.1** adds the whole `build-and-validate` job and puts it in the branch ruleset. `lint-and-test` is added to the ruleset in M1.5, in the same pull request that introduces the job — a required check that never reports would block every pull request.

The `container.image` digest in this file is rewritten by `toolchain.yml` whenever a new image is published (§3.6), and `tests/unit/test_workflows_pinned.py` fails the build if it ever stops matching `tools/TOOLCHAIN_DIGEST`, if any action is left on a floating tag, or if a job container names a tag rather than a digest.

If the full P1 build (first catalog PRs, empty manifest on `main`) exceeds the 45-minute budget, split `build-and-validate` into a matrix over `--group {media,data,other}` and a final `manifest check` job that downloads the artifacts.

### 3.2 `deploy.yml` — push to `main` only

```yaml
name: deploy
on:
  push: { branches: [main] }
  workflow_dispatch: { inputs: { force_site: { type: boolean, default: false }, apply_infra: { type: boolean, default: false } } }
concurrency: { group: deploy, cancel-in-progress: false }
permissions: { contents: read }
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    container: { image: "ghcr.io/<OWNER>/loremfile-toolchain@sha256:<DIGEST>" }
    timeout-minutes: 60
    env:
      CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      CLOUDFLARE_ACCOUNT_ID: ${{ vars.CLOUDFLARE_ACCOUNT_ID }}
      CLOUDFLARE_ZONE_ID: ${{ vars.CLOUDFLARE_ZONE_ID }}
      AWS_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
      AWS_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
      R2_BUCKET: ${{ vars.R2_BUCKET }}
    steps:
      - uses: actions/checkout@<SHA-v4>
        with: { fetch-depth: 0 }
      - run: pip install -e . --no-deps
      - run: loremfile build --missing-in-bucket -j 4   # regenerate only active manifest entries whose key is absent from R2 (usually just the fixtures merged since the last deploy)
      - run: loremfile validate
      - run: loremfile manifest check                    # regenerated bytes must equal the committed manifest; the manifest is never rewritten here
      - run: loremfile site build
      - run: loremfile upload --fixtures                 # missing keys only; refuses to overwrite an existing key with different bytes
      - run: loremfile upload --apply-removals           # only objects whose manifest entry is status: removed (takedown flow); no-op otherwise
      - run: loremfile upload --site ${{ inputs.force_site && '--force-site' || '' }}
      - run: loremfile purge --site
      - id: infra_changed
        run: |
          base="${{ github.event.before }}"
          if [ "$base" = "0000000000000000000000000000000000000000" ] || ! git cat-file -e "$base" 2>/dev/null; then base="$(git rev-parse HEAD~1)"; fi
          if git diff --name-only "$base" "${{ github.sha }}" -- infra/ | grep -q .; then echo "changed=true" >> "$GITHUB_OUTPUT"; fi
      - run: loremfile infra apply --dry-run
      - name: Apply infra when infra/ changed or requested
        if: steps.infra_changed.outputs.changed == 'true' || inputs.apply_infra == true
        run: loremfile infra apply
      - run: loremfile infra audit
      - run: loremfile verify-live --mode smoke
```

Ordering rationale: fixtures first (immutable, safe to be early), removals next (rare), then site (references fixtures), then purge, then infra, then verification. A failure at any step stops the job; nothing after "upload --fixtures" can undo a fixture upload, and nothing needs to (immutability).

### 3.2b `infra.yml` — on demand (maintainer operations without local credentials)

```yaml
name: infra
on:
  workflow_dispatch:
    inputs:
      mode: { type: choice, options: [audit, apply, probe, restore, redact], default: audit }
      restore_archive_url: { type: string, default: "" }   # restore mode only; must start with https://github.com/<OWNER>/loremfile/releases/download/ — the tool refuses any other origin
      restore_only: { type: string, default: "" }          # optional comma-separated paths
      redact_path: { type: string, default: "" }           # fixture path, redact mode only
permissions: { contents: write }                            # write only for redact (re-uploading release assets); other modes do not touch the repository
jobs:
  run:
    runs-on: ubuntu-latest
    environment: production
    container: { image: "ghcr.io/<OWNER>/loremfile-toolchain@sha256:<DIGEST>" }
    timeout-minutes: 60
    env: { <same env block as deploy.yml> }
    steps:
      - uses: actions/checkout@<SHA-v4>
      - run: pip install -e . --no-deps
      - if: inputs.mode == 'audit'
        run: loremfile infra audit
      - if: inputs.mode == 'apply'
        run: loremfile infra apply && loremfile infra audit
      - if: inputs.mode == 'probe'
        run: loremfile probe --up && loremfile probe --check && loremfile probe --down
      - if: inputs.mode == 'restore'
        run: loremfile upload --restore "${{ inputs.restore_archive_url }}" ${{ inputs.restore_only != '' && format('--only {0}', inputs.restore_only) || '' }} && loremfile verify-live --mode full
      - if: inputs.mode == 'redact'
        env: { GH_TOKEN: ${{ github.token }} }
        run: loremfile release redact --path "${{ inputs.redact_path }}"
```

This is how M2.3 (`apply`), M2.4 (`probe`), rotation checks (`audit`) and restores run: tokens never leave GitHub. The probe mode uploads `_probe/index.html`, `_probe/ok.txt`, `_probe/page.html`, `_probe/dir/index.html` and `_probe/missing-404-check` is a GET of a non-existent key; it asserts `/`, `/_probe/`, headers (files, markup, page), CORS preflight, `www` redirect, 404 cache TTL (`cf-cache-status` and `age` on a repeated 404), and the rate limit (400 requests in 10 s → at least one 429, then 200 after 10 s); then deletes `_probe/*`. Deletion is limited to that prefix in code.

### 3.3 `health.yml` — daily

```yaml
name: health
on:
  schedule: [{ cron: "17 4 * * *" }]
  workflow_dispatch: { inputs: { inject_failure: { type: string, default: "" } } }   # REQ-27 test: pass any manifest path to simulate a failure
permissions: { contents: write, issues: write }     # contents: write only for the Monday ops-log commit
jobs:
  check:
    runs-on: ubuntu-latest
    environment: production                          # for the read-only analytics token
    container: { image: "ghcr.io/<OWNER>/loremfile-toolchain@sha256:<DIGEST>" }
    timeout-minutes: 30
    env: { CLOUDFLARE_ANALYTICS_TOKEN: ${{ secrets.CLOUDFLARE_ANALYTICS_TOKEN }}, CLOUDFLARE_ACCOUNT_ID: ${{ vars.CLOUDFLARE_ACCOUNT_ID }}, CLOUDFLARE_ZONE_ID: ${{ vars.CLOUDFLARE_ZONE_ID }} }
    steps:
      - uses: actions/checkout@<SHA-v4>
      - run: pip install -e . --no-deps
      - run: loremfile site build                       # deterministic for a given commit; its hashes are the site-integrity baseline (never read from the bucket)
      - id: verify
        run: loremfile verify-live --mode daily --json ${{ inputs.inject_failure != '' && format('--inject-failure {0}', inputs.inject_failure) || '' }} > health.json || echo "failed=true" >> "$GITHUB_OUTPUT"
      - name: Open or update issue on failure, close on recovery
        env: { GH_TOKEN: ${{ github.token }} }
        run: python -m loremfile.gh_issue --label health --title "Health check failing" --report health.json --state ${{ steps.verify.outputs.failed == 'true' && 'failing' || 'ok' }}
      - name: Usage and cost check (R2 operations month-to-date, zone requests, hit ratio)
        env: { GH_TOKEN: ${{ github.token }} }
        run: loremfile usage --json > usage.json && python -m loremfile.gh_issue --label cost --title "R2 operations above threshold" --report usage.json --state $(python -c "import json;print('failing' if json.load(open('usage.json'))['summary']['r2_class_b_mtd']>5_000_000 else 'ok')")
      - name: Token rotation reminder (30 days before any expiry recorded in infra/token-expiry.json)
        env: { GH_TOKEN: ${{ github.token }} }
        run: loremfile tokens-due --json > tokens.json && python -m loremfile.gh_issue --label rotation-due --title "Token rotation due" --report tokens.json --state $(python -c "import json;print('failing' if json.load(open('tokens.json'))['summary']['due']>0 else 'ok')")
      - name: Weekly ops-log heartbeat (Mondays) on the unprotected ops-log branch — also keeps scheduled workflows alive
        if: github.event_name == 'schedule'
        run: |
          if [ "$(date -u +%u)" = "1" ]; then
            git config user.name loremfile-bot && git config user.email bot@loremfile.dev
            git fetch origin ops-log && git checkout ops-log || { git checkout --orphan ops-log && git rm -rfq . ; }
            python -m loremfile.ops_log --from usage.json --append ops-log.md
            git add ops-log.md && git commit -m "ops-log: weekly numbers" && git push origin ops-log
          fi
```

`loremfile usage` queries the GraphQL Analytics API (`r2OperationsAdaptiveGroups` for Class A/B operations month-to-date on the bucket; zone HTTP request totals and cache-status breakdown for the last 7 days) with the read-only T4 token; `verify-live` treats a 429 from our own rate limit as "retry after 10 s", not as a failure. The ops-log commit goes to the dedicated **`ops-log` branch**, which carries no ruleset, so `main` keeps its pull-request requirement and no bypass is granted to any workflow (rulesets bypass by actor, not by path — a bypass for the Actions app would have applied to every workflow). `GITHUB_TOKEN` with `contents: write` can push only to unprotected branches. GitHub's 60-day rule speaks of "repository activity"; a push to any branch is repository activity. Should the rule turn out to count only default-branch commits (**[VERIFY]** by observing the workflow still runs after the first quiet 60 days), the weekly session's merged PRs keep `main` active anyway and the runbook's re-enable step covers the rest. The ops-log is read at `https://github.com/<OWNER>/loremfile/blob/ops-log/ops-log.md`.

`verify-live --mode daily` = HEAD every manifest path (parallel, 16 workers, rate ≤ 20 rps to stay under our own limit) comparing `Content-Length` and `Content-Type`; GET + SHA-256 for all fixtures < 1 MB and a rotating 5 % sample of larger ones (rotation = day-of-year modulo); full header contract on one fixture per format (the smallest P1 fixture of that format by bytes, ties broken by path order); the encoded-path and warm-cache CORS probes from `08` §6; every site key hashed against the **rebuild of the checked-out commit** in `build/site/` (defacement check — the baseline must never come from the bucket, because whoever holds T2 can rewrite any site key including any manifest stored there; a mismatch during the few minutes between a merge and its deploy is tolerated by retrying once after 10 minutes); discovery files; `www` redirect; RDAP expiry ≥ 45 days; TLS certificate expiry ≥ 14 days; `security.txt` `Expires` ≥ 30 days; total time reported. `gh_issue.py` de-duplicates by label + title, appends a comment per failing day, and closes with a comment on the first green run.

### 3.4 `audit.yml` — weekly (Mondays) and on demand

Runs `loremfile infra audit` (unreadable settings are warnings; opens/updates an `infra-drift` issue only on real differences) and, on the first Monday of each month, `loremfile build --all --audit -j 4` (opens/updates a `determinism` issue on drift). Uses the `production` environment for the T1 token because Cloudflare tokens cannot be split read/write per call; the job's steps never call apply.

### 3.5 `release.yml` — on tag `v*`

1. Checks out the tag; verifies `manifest.json.catalog_version` equals the tag.
2. Finds the previous release tag with `git describe --tags --abbrev=0 <tag>^` (none for `v1.0.0`).
3. `loremfile release archive --since <previous tag>` (or `--snapshot` for the first release and for every 10th minor release): downloads the fixtures added since the previous release **from production** (not regenerated), verifies each against the manifest hash, and writes `fixtures-<from>-<to>.tar` (uncompressed; contents are already compressed or incompressible) plus `manifest.json`, `sha256sums.txt` and a `CHANGELOG` excerpt. Archives are split at 1.5 GB into `…part1.tar`, `…part2.tar` with a `parts.txt` listing the parts and their SHA-256, so every asset stays under GitHub's 2 GB limit.
4. `gh release create v<version> --notes-file …` with the assets attached (needs `permissions: contents: write`).

### 3.6 `toolchain.yml` — on changes under `tools/`

Triggered by a push touching `tools/Dockerfile`, `tools/apt-versions.txt`, `tools/requirements.lock`, `tools/smoke.sh` or the workflow itself, and by `workflow_dispatch`. Permissions are per job and least-privilege: the `build` job takes `contents: read, packages: write`; only `propose-digest-bump` takes `contents: write, pull-requests: write`.

`build` builds `tools/Dockerfile`, pushes to `ghcr.io/<OWNER>/loremfile-toolchain:<git-sha>` (**no `latest` tag** — workflows reference the image by digest and a moving tag would be a mutable surface), then smoke-tests **the pushed digest**, not a local build:

1. `tools/smoke.sh` inside the image — asserts every apt version matches `tools/apt-versions.txt`, all twelve ffmpeg encoders are present, SQLite answers an FTS5 `MATCH`, 31 Python modules import, `zstandard` round-trips, and the four determinism environment variables are set. It exits non-zero on the first failure.
2. `pip install -e .` with the repository mounted, then `import loremfile` — the image deliberately does **not** contain the package (the repository is mounted at run time), so this proves the image can still host it.

**Corrected in M1.3:** an earlier draft of this section said the workflow writes `dpkg -l > tools/apt-versions.txt`. It must not. That file is the pinned *input* the Dockerfile installs from and `smoke.sh` checks against; having the build overwrite it would be circular and would silently launder a drifted version into the pin. The full inventory (`dpkg-query` of every package, plus `pip freeze` and the image reference) is uploaded as the `toolchain-provenance` artifact instead, and `apt-versions.txt` changes only in a reviewed pull request.

`propose-digest-bump` runs **only on `main`**. If the new digest differs from `tools/TOOLCHAIN_DIGEST` it creates a branch updating that file and every `image:` line in the workflows, runs `loremfile manifest update` when a manifest and the CLI both exist (they do not before M1.6, so the step is conditional), and opens the pull request with `gh pr create` using `GITHUB_TOKEN` — no third-party action. CI on that pull request runs the determinism tests against the new image. On any other branch the author is already inside a pull request, so the digest is copied by hand from the job summary, which prints the exact line to paste.

Run it once in M1.3 before enabling `ci.yml`.

## 4. Dependabot — `.github/dependabot.yml`

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /tools
    schedule: { interval: weekly }
    groups: { python-deps: { patterns: ["*"] } }
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
  - package-ecosystem: docker
    directory: /tools
    schedule: { interval: weekly }
```

Python updates change `requirements.in`; the PR must also regenerate `requirements.lock` (`pip-compile --generate-hashes`) and bump the toolchain digest — `tools/check_lock.sh` in `ci.yml` fails if `requirements.in` differs from the merge-base while `requirements.lock` or `TOOLCHAIN_DIGEST` do not.

## 5. Uploader contract (`loremfile upload`)

- S3 client: `boto3`, `endpoint_url=https://<ACCOUNT_ID>.r2.cloudflarestorage.com`, `region_name="auto"`. If uploads fail with a checksum-related error on a newer boto3, set `AWS_REQUEST_CHECKSUM_CALCULATION=when_required` and `AWS_RESPONSE_CHECKSUM_VALIDATION=when_required` (R2 now supports CRC64NVME full-object checksums, so this should not be needed; the flag is documented here in case).
- **Fixtures** (`--fixtures`): for each manifest entry with `status: active`, `HEAD` the key. Missing → the bytes must exist in `build/fixtures/` (produced by `build --missing-in-bucket`) or the job fails; upload with `ContentType`, `CacheControl` (fixture value), `ContentDisposition: inline; filename="<last path segment>"`, `Metadata: {sha256, catalog-version}`; multipart (16 MiB parts, 8 threads) for objects > 16 MiB. Present → compare the stored `sha256` metadata with the manifest; equal → skip; different → **fail the job** (immutability).
- **Removals** (`--apply-removals`): for each manifest entry with `status: removed` whose key still exists, `DeleteObject` and purge the URL. This is the only delete in the tool besides `probe --down` (prefix `_probe/`); the code refuses any other key.
- **Site** (`--site`): upload every file under `build/site/` with the content-type table (`html`→`text/html; charset=utf-8`, extensionless→`text/html; charset=utf-8`, `json`→`application/json`, `txt`→`text/plain; charset=utf-8`, `xml`→`application/xml`, `css`→`text/css; charset=utf-8`, `js`→`text/javascript; charset=utf-8`, `svg`→`image/svg+xml`, `png`→`image/png`, `schema/*.json`→`application/schema+json`) and cache-control per `02` §4. Skip unchanged (compare sha256 metadata) unless `--force-site`.
- **Restore** (`--restore <archive> [--only …]`, `--from-dir <dir>`): `--restore` accepts only URLs under `https://github.com/<OWNER>/loremfile/releases/download/` (or a local file); read fixtures from the release archive or directory, verify each against the manifest, upload where the live object is missing; where a live object exists with a different hash the overwrite is attempted and, under a bucket lock, refused by R2 — the tool reports each refusal explicitly and the owner must lift that prefix's lock rule first (same ceremony as a takedown, `11` §7.8). A hash-differing object under an intact lock should never exist.
- `--dry-run` prints the plan without writing; every mode prints counts: uploaded/skipped/removed/failed and total bytes.

## 6. Cache purge (`loremfile purge --site`)

`POST /zones/{zone_id}/purge_cache` with `{"prefixes": ["loremfile.dev/docs/", "loremfile.dev/legal/", "loremfile.dev/assets/"]}` plus `{"files": [ ...absolute URLs... ]}` for the root, format pages (both `/pdf` and `/pdf/`), discovery files and per-format `index.json`, in batches of 100 operations (the Free-plan per-request maximum; purge by prefix, hostname and tag are available on all plans). Fixtures and `schema/` are never purged (immutable) except in the takedown flow, which purges the removed URL.

## 7. Release and versioning

- `catalog_version` is semver in `manifest.json` and `CHANGELOG.md`. **Minor** = fixtures added or removed (tombstoned); **patch** = descriptions, tags, notes, deprecation flags or site-only changes (`props`, `bytes`, `sha256`, `mime` never change); **major** = manifest schema or URL contract change (never removes anything).
- Tags `v1.2.0` are created by the maintainer after the deploy that introduced the fixtures is green; `release.yml` runs.
- `CHANGELOG.md` follows Keep a Changelog; every fixture addition lists the path.

## 8. Pull request template (excerpt)

```
## What
- [ ] New fixtures (list paths)  - [ ] Site/docs  - [ ] Infra  - [ ] Toolchain

## Checklist
- [ ] `loremfile catalog validate` passes locally
- [ ] Every new fixture has description, tags, expect, size_class
- [ ] No third-party content, no real personal data, no private keys, no executables, no external entities (13-legal-and-policy.md §5)
- [ ] I did not modify any existing manifest entry (immutability)
- [ ] CHANGELOG updated
```

## 9. AGENTS.md (checked into the repo root; instructions for coding agents)

Contains: the CLI commands, the immutability rule in bold, "never edit manifest.json by hand — run `loremfile manifest update` in the container and commit the result", "always run inside the toolchain image", "never commit secrets or generated binaries", "placeholders `<OWNER>` live in `config.py` and workflows; replace with `grep -rn '<OWNER>'` once Q-03 is answered", the PR checklist, and a pointer to `docs/15-implementation-plan.md` for task order.

## 10. Takedown support in the release flow (`loremfile release redact`)

A removed fixture must also disappear from public GitHub Release assets. `loremfile release redact --path <path>` downloads every release archive that contains the path (from `parts.txt`/archive indexes), rebuilds the archive without it, re-uploads with `gh release upload --clobber`, updates `parts.txt` and the release notes with a "redacted <path> on <date>" line, and keeps the tombstone in `sha256sums.txt`. Runs from `infra.yml` (mode `redact`, input `redact_path`) so it needs no local credentials beyond `GITHUB_TOKEN` (`contents: write`).
