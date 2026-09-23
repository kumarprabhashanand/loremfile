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

**Applied in M1.5 and verified by reading the settings back.** Ruleset id `22459996`, name `main`, enforcement `active`, targeting `~DEFAULT_BRANCH`; `GET /repos/{owner}/{repo}/rules/branches/main` confirms all five rules apply. Two things worth knowing that the table above does not say:

- GitHub adds **`require_extra_approval_for_unattributed_changes: true`** to the `pull_request` rule by default, and it was left on. It does not conflict with `required_approving_review_count: 0` for ordinary pull requests — old PR #5 was `MERGEABLE`/`CLEAN` under it — but a pull request containing commits authored by someone other than the person merging can need one approval. The automated digest-bump pull request from `toolchain.yml` is authored by `github-actions[bot]`, so expect to approve that one. Turn the parameter off if that friction is not wanted; leaving it on is the safer default and costs one click.
- Actions permissions are `allowed_actions: selected` with `github_owned_allowed` and `verified_allowed` (no `patterns_allowed`), **plus `sha_pinning_required: true`** — GitHub now enforces SHA pinning at the repository level, so the platform rejects a floating tag as well as `tests/unit/test_workflows_pinned.py`. Default workflow permissions were already `read`.

Security features were **all off** on the fresh repository and were enabled in M1.5: secret scanning, secret-scanning push protection, Dependabot alerts, Dependabot security updates, private vulnerability reporting. `secret_scanning_non_provider_patterns` and `secret_scanning_validity_checks` remain off — neither is needed for a repository that holds no credentials.

Repository variables set in M1.5: `R2_BUCKET=loremfile-public`, `SITE_HOST=loremfile.dev`. `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_ZONE_ID` are **not knowable until M0.4** and are deliberately unset; the `production` environment exists with a deployment branch policy of `main` only, and holds no secrets yet.

## 2. Secrets and variables

| Name | Kind | Scope | Source | Rotation |
|---|---|---|---|---|
| `CLOUDFLARE_API_TOKEN` | secret | env `production` | T1 (`08` §2.9) | 180 days |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | secrets | env `production` | T2 | 180 days |
| `CLOUDFLARE_ANALYTICS_TOKEN` | secret | env `production` | T4 (read-only) | 365 days |
| `R2_READ_TOKEN` | secret | env `production` | T5 (Admin Read only, `08` §2 step 10c); read by `audit_bucket_locks` alone | 180 days |
| `FORBIDDEN_STRINGS` | secret, optional | env `production` | the owner — one string per line that must never appear in the tree; the site build's git-grep guard fails if one does. **The list lives only here**: committed, it would publish what it protects | n/a |
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

**The toolchain digest lives in exactly one place (changed in M2).** `tools/TOOLCHAIN_DIGEST` is read by a small `setup` job in each workflow, which publishes it as an output; every containerised job then declares `needs: setup` and uses `container.image: ${{ needs.setup.outputs.digest }}`.

Before this, `ci.yml` and `infra.yml` each carried a literal copy and `toolchain.yml` kept them in step with a `sed` over `.github/workflows/*.yml`. That rewrite is why `propose-digest-bump` needed `workflows: write`, which `GITHUB_TOKEN` does not have — so **every digest bump was rejected**: `refusing to allow a GitHub App to create or update workflow .github/workflows/ci.yml`. The duplication was invisible until the automation that depended on it actually ran.

The pattern was verified before the workflows were rewritten around it: a throwaway workflow confirmed that `container.image` accepts `needs.*.outputs.*` on GitHub-hosted runners and that the runner pulls and creates the container from it. `tests/unit/test_workflows_pinned.py` now fails if any workflow names a toolchain image literally — on a `container.image` line or anywhere else — and if a job uses the output without depending on `setup`, because that expression resolves to an empty string and GitHub then runs the job on the bare runner instead of failing.

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
    container: { image: "ghcr.io/kumarprabhashanand/loremfile-toolchain@sha256:<DIGEST>" }
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
    container: { image: "ghcr.io/kumarprabhashanand/loremfile-toolchain@sha256:<DIGEST>" }
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
        with: { name: fixture-inventory, path: inventory.txt, retention-days: 90 }   # M3.1: hashes, not bytes
      - name: Manifest diff for the author
        if: failure()
        run: loremfile manifest check --json | python -m loremfile.ci_summary --explain >> "$GITHUB_STEP_SUMMARY"   # prints the exact entries to commit when a committed entry does not match
```

**Fixture artifact, changed in M3.1 and again in M3.6.** The listing above uploads `build/fixtures` as a `new-fixtures` artifact on non-fork pull requests. That directory is already **243 MB** at M3.1 and would be roughly **595 MB** at launch, uploaded on every pull request against a free-tier storage quota. `build-and-validate` therefore uploads a 4 KB `fixture-inventory` — every path with its size and sha256 — which is what a reviewer actually reads.

**The listing above was wrong for two days, and it still cost something.** M3.1 replaced `new-fixtures` with `fixture-inventory` and did not update this listing in the same pull request. When M3.6 needed to know whether the bytes were being retained, the doc said they were — for 7 days — so the proposed fix was to raise that retention. There was nothing to raise: the bytes had never been stored at all, and five manifest entries were already describing bytes that existed nowhere. The listing now matches the workflow, and the CI guard in `manifest check` exists because a doc cannot be relied on to notice this for us.

**M3.6 added a second, targeted artifact, and it is not an optimisation.** Fixtures marked `expected_drift` cannot be rebuilt byte for byte on different hardware (`06` §4), so for those paths the manifest describes bytes that exist **nowhere else** between the pull request and the deploy. `carry-forward-fixtures` holds exactly those files — five paths, about **69 MB** — with **90-day retention**, alongside the inventory that records which CPU produced them. Dropping it, or letting it expire before the deploy runs, makes those manifest entries unfulfillable: regeneration drifts and there is nothing to fall back to, and the fixtures would have to be re-catalogued at new paths before they could ever be published. Retention is therefore a **correctness** setting here, not a convenience.

**Retention measured, 2026-09-10, and it is not the constraint people assume.** Read off the artifacts themselves rather than off this workflow's `retention-days:`, because a repository or organisation maximum silently clamps that value:

| | |
|---|---|
| Created | `2026-09-10T13:19:50Z` |
| Expires | `2026-12-09T13:15:20Z` |
| **Effective retention** | **90 days** — the requested value was honoured |

But the 90 days do not run from M3.6. **Every `ci.yml` run rebuilds and re-uploads the artifact**, so the newest copy is always ~90 days from the most recent pull request, not from the run that first catalogued anything. What actually binds is the *pairing*: an artifact is only useful together with manifest entries built in the **same run**. Three distinct artifact sizes have been observed across runs — 68,840,997, 68,841,346 and 68,843,383 bytes — which is RISK-21 visible in the artifact listing: each run's bytes differ, so each run's artifact satisfies only its own entries.

The consequence is a shorter deadline than "90 days from now": **from the moment `manifest adopt` records entries from a run, only that run's artifact can fulfil them, and its own 90 days apply.**

**And the claim that this window is "minutes, because the deploy follows the merge" is not true yet.** It will be once `push: branches: [main]` is enabled. Today the deploy is dispatch-only by our own decision (above), so it follows *someone remembering to dispatch it* — which means adopting entries opens a 90-day clock that nothing is watching. That is the same shape as the failure this whole detour came from. Until the trigger is enabled, the window is closed procedurally instead: **`11` §7.9b requires the pull request that adopts the entries and the dispatch that publishes them to happen in the same working session.**

If having all the bytes ever becomes worth paying for the storage, it is a three-line change; see `19` for the cost picture.

**How this file is built up (M1.5 onwards).** The listing above is the finished workflow. Each step is added by the milestone that creates the thing it checks, so the job never calls a command that does not exist yet: **M1.5** landed `lint-and-test` with checkout, `pip install -e .`, ruff, `mypy src/` and `pytest tests/unit`; **M1.6** added `tools/check_lock.sh` and `loremfile catalog validate` to the same job; **M3.1** adds the whole `build-and-validate` job and puts it in the branch ruleset. `lint-and-test` is added to the ruleset in M1.5, in the same pull request that introduces the job — a required check that never reports would block every pull request.

The `container.image` digest in this file is rewritten by `toolchain.yml` whenever a new image is published (§3.6), and `tests/unit/test_workflows_pinned.py` fails the build if it ever stops matching `tools/TOOLCHAIN_DIGEST`, if any action is left on a floating tag, or if a job container names a tag rather than a digest.

If the full P1 build (first catalog PRs, empty manifest on `main`) exceeds the 45-minute budget, split `build-and-validate` into a matrix over `--group {media,data,other}` and a final `manifest check` job that downloads the artifacts.

### 3.2 `deploy.yml` — push to `main` only

**Two blocking gates before any object is written (added M3.6).**

1. **No upload to an unlocked prefix.** `upload --fixtures` refuses, and the job fails, if any prefix it is about to write is not covered by a rule in `infra/r2-locks.json` as applied to the bucket. Locks are deferred through M3 so that pre-publication mistakes stay correctable (`08` §2), and that argument expires precisely here: a first deploy onto an unlocked bucket leaves published fixtures mutable by a leaked T2, which is the threat ADR-023 exists to close. The gate is what stops the deferral outliving its reason.
2. **No regeneration of `expected_drift` paths.** Those bytes cannot be rebuilt on other hardware (`06` §4), so the deploy consumes the `carry-forward-fixtures` artifact for them and **fails if it is absent or does not match the manifest** rather than substituting a rebuild.

```yaml
name: deploy
on:
  push: { branches: [main] }
  workflow_dispatch: { inputs: { force_site: { type: boolean, default: false }, apply_infra: { type: boolean, default: false } } }
concurrency: { group: loremfile-zone, cancel-in-progress: false }   # shared with infra.yml and audit.yml's infra job (ADR-029)
permissions: { contents: read, actions: read }                        # actions: the carry-forward artifact, and the run list infra_changed reads
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    container: { image: "ghcr.io/kumarprabhashanand/loremfile-toolchain@sha256:<DIGEST>" }
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
      - id: infra_changed                              # base: the last successful push deploy on main — not HEAD~1, not event.before (ADR-029)
        env: { GH_TOKEN: "${{ github.token }}" }
        run: loremfile infra changed --exclude-run "$GITHUB_RUN_ID" --head "$GITHUB_SHA" >> "$GITHUB_OUTPUT"
      - run: loremfile infra apply --dry-run
      - name: Apply infra when infra/ changed or requested
        if: steps.infra_changed.outputs.changed == 'true' || inputs.apply_infra == true
        run: loremfile infra apply
      - run: loremfile infra audit
      - run: loremfile verify-live --mode smoke
```

Ordering rationale: fixtures first (immutable, safe to be early), removals next (rare), then site (references fixtures), then purge, then infra, then verification. A failure at any step stops the job; nothing after "upload --fixtures" can undo a fixture upload, and nothing needs to (immutability).

**When `Apply infra` runs (ADR-029).** On `mode: deploy`, when `apply_infra` is ticked or `infra/` changed since the commit the zone last converged to: the head SHA of the most recent successful `push` run of this workflow on `main`, other than the current run (`loremfile infra changed`). Not `HEAD~1`, and not `github.event.before`, which is the same commit for a squash merge: a pending deploy replaced in the concurrency group never runs, so an `infra/` change in its commit is invisible from a newer commit that does not touch `infra/` itself. No earlier successful push run means changed; a lookup that fails fails the step. It deliberately does not apply on every deploy — an apply converges `security_level` and would switch off Under Attack Mode mid-incident (`11` §7.4).

**After a history rewrite.** A rewrite replaces every commit SHA, so the last successful push deploy names a commit the checkout no longer has, and `infra changed` would be `Undecided` on every deploy from then on. `changed.HISTORY_REWRITTEN_AT` is the cutoff: when set, a run created before it is never a base, so the first push deploy after the rewrite finds none and counts `infra/` as changed — `apply` compares before it writes, so it should change nothing. A base created **after** the cutoff that the checkout lacks is still `Undecided`: that is not the rewrite, and the step must stop. Unset, the constant has no effect; it is set in the rewrite's own commit, to the rewrite time.

**What `apply` writes, and why `infra audit` still does not reuse its report.** `apply` reads before it writes; until 2026-09-15 it PUT the five ruleset phases and PATCHed tiered cache unconditionally, reporting `updated` for all six on every run, drift or none.

| Resource | Written only when | Otherwise reported |
|---|---|---|
| `http_request_dynamic_redirect` (1 rule), `http_request_transform` (2), `http_response_headers_transform` (4), `http_request_cache_settings` (1), `http_ratelimit` (1) | `apply.compare_rules` finds a difference, or the phase has no entry point yet (404) — then one full `PUT` of the phase | `unchanged`, "N rule(s) match". A 403 is `manual`; any other unreadable answer is `failed` and **not written**, because there is nothing to compare against |
| `tiered-cache` (`smart topology on`) | the topology is not already `on` — then one `PATCH` | `unchanged` |

`compare_rules` drops the fields Cloudflare assigns (`id`, `version`, `last_updated`; `ref` is ours and compared — the live zone preserves every committed ref) and compares only the fields the committed rule declares, in order. Every declared leaf of every committed rule is mutated in `tests/unit/test_infra_apply.py` to prove the comparison catches it. `infra audit` calls the same function but reports from its own reads, never from `apply`'s outcomes (§3.4), so its `drift` does not depend on every writer comparing first.

**As implemented in M4.4, and what it does not yet carry.** The workflow above is the target. What landed differs in five places, each recorded here rather than left for a reader to discover from a red cross:

| Deferred | Why | Returns with |
|---|---|---|
| ~~`loremfile site build`, `upload --site`, `purge --site`~~ | — | ✅ **M4.1**: built with the legal values, published, purged, then `verify-live --site-dir build/site` |
| ~~`loremfile infra audit`~~ | — | ✅ **`audit.yml`**, weekly and on dispatch, in the `loremfile-zone` group; not a deploy step |
| `-j 4` on the build | `-j` is not implemented and the measurement in `06` §11 says it need not be yet | M7 |
| ~~`push: branches: [main]`~~ | **A judgement, not a missing command** — see below | ✅ **enabled 2026-09-10** |

**Why the trigger was deferred, and what discharged it.** Per-merge deployment is the steady state (`15` M3) and this workflow is built for it. But its first run was also the first time `loremfile upload` had ever addressed a bucket, and its writes land under **indefinite lock rules**: published, locked, permanent. A first exercise that is also an irreversible one is the wrong order — the same caveat `release.py` carries, that a green unit suite is not evidence about a path which has never seen a real object. So the workflow shipped dispatch-only with `mode` defaulting to `dry-run`.

**Condition met, and the trigger enabled, 2026-09-10.** Four runs, each reviewed before the next was dispatched:

| # | Run | Result |
|---|---|---|
| 1 | `mode: dry-run`, whole manifest | 161 planned, 414,208,239 bytes, **0 written**; both gates satisfied; carry-forward resolved all five `expected_drift` paths by content |
| 2 | `mode: deploy`, `only:` 10 paths across 10 prefixes | `written=10`, `verify-live failing=0`; all seven header values matched §4.1 of `03`, `Timing-Allow-Origin` included |
| 3 | `mode: deploy`, `only: csv/people-100k.csv` | the **multipart** path: `written=1`, `failing=0`, seven headers byte-identical to run 2 |
| 4 | `mode: deploy`, whole manifest | `uploaded=150, skipped=11, written=150, failed=0`; smoke checked 50 of 161, 0 failing |

Run 4's `skipped=11` is the part worth keeping: the plan HEADed the already-published objects, compared their `sha256` metadata with the manifest, matched, and skipped. The immutability comparison has now run against real R2 rather than a fake.

**The bug enabling it nearly shipped, recorded here because the next dispatch-only mode will reach for the same expression.** The workflow's `if:` conditions and `--dry-run` flag were written as `inputs.mode == 'deploy'` / `inputs.mode == 'dry-run'` while it was dispatch-only, where they were correct. **On a `push` event `inputs.mode` is the empty string**, so the moment `push` was enabled both comparisons would have been false: `Publish fixtures` would still have run *without* `--dry-run` — a real upload — while `Verify what was published` and `Apply infra` were silently skipped. **A green deploy that verified nothing**, and it could only manifest on the first push, never on any of the four dispatches that preceded it. The fix resolves the mode once, at job level — `MODE: ${{ inputs.mode || 'deploy' }}` — and every condition reads `env.MODE`.

Confirmed on the first push, run `34525369410` (merge of old PR #49): `Publish fixtures` ran with `dry_run=False` (`skipped=161, written=0` — a correct no-op), and `Verify what was published` **ran** rather than being skipped (`mode=smoke, checked=50, failing=0`). `Apply infra` was skipped for the right reason: `infra/` had not changed.

**The rule for the next person:** any workflow input read by a job that can also be triggered without inputs must be defaulted where it is resolved, not compared where it is used. `inputs.x == 'y'` in an `if:` is a condition that silently becomes `false` on every event type that does not carry `x`.

**Enabling it also closes a window.** Fixtures marked `expected_drift` are fulfillable only by the artifact of the run that built them, so adopting their manifest entries starts a 90-day clock. While publication depended on someone remembering to dispatch, that clock could start with nobody watching it — the shape that withdrew those five entries in the first place. With `push` enabled, the pull request that adopts them deploys them in the same cycle, and `11` §7.9b's same-session rule becomes "merge and read the run".

**The staged first publish.** `--only` narrows both the publish and the verification. The header contract in `03` §4.1 lives in object metadata written at upload — `Content-Type`, `Cache-Control`, `Content-Disposition` — and the bucket lock freezes it there, so it has exactly one chance to be right, and until the first real upload it had only ever been exercised against a fake S3 client. Stage one publishes ten small fixtures across ten prefixes and then verifies exactly those paths:

`pdf/minimal.pdf`, `svg/simple-shapes.svg`, `png/1x1.png`, `csv/people-10-semicolon.csv`, `json/all-types.json`, `xml/with-namespaces.xml`, `txt/lorem-1kb.txt`, `bin/1-byte.bin`, `mp3/sine-440hz-3s.mp3`, `docx/with-table.docx`

They are chosen for the branches they cross, not for coverage of the catalog: a PDF (which must carry **no** CSP) and two markup types (which must carry the sandbox CSP), types whose charset is part of the MIME and types that are opaque bytes, and ten distinct prefixes so the lock gate is exercised ten times. All are under the 16 MiB multipart threshold **on purpose** — `upload_file` splits there and sets metadata at initiate rather than per part, which is a different code path, so it gets **stage two on its own**: `csv/people-100k.csv`, the smallest object above the threshold. Only then the remaining fixtures. `tests/unit/test_deploy_path.py` pins the list, so a renamed path fails there rather than half-way through a dispatch.

`--only` narrows the *plan*, not the checks: a staged publish runs the same lock and carry-forward gates over exactly the keys it is about to write. `verify-live --only` overrides `--mode`, because `smoke` samples one fixture per format from the whole manifest and most of the manifest is not published yet.

**Result, 2026-09-10.** Stage one: 10 objects, 92,519 bytes, `written=10`, `verify-live failing=0`; all seven header values matched `03` §4.1, `Timing-Allow-Origin` included, so rule H1 reaches published objects and not only 404s. Stage two: `csv/people-100k.csv`, 25,395,296 bytes over the multipart path, `written=1`, `failing=0` — **the seven headers are byte-identical to stage one's**, so metadata set at multipart initiate survives to the response. The one difference is the `ETag`: `"0fb5712e2d6fa8cae82c86acc1e2dabf-2"` against a plain 32-hex digest on a single-part object. That is `03` §4.1's "do not assume it is an MD5" stated by a published object rather than by a warning.

**What the staged runs did *not* verify, which a green result must not be read as covering.** `http_response_headers_transform` holds three rules and the eleven published objects reach one and a half of them:

| Rule | Expression | Status after staging |
|---|---|---|
| H1, headers on every object with an extension | `contains "." and not ends_with("/index.html")` | **positive half verified** on 11 objects; the `/index.html` **exclusion is not** — no such object exists |
| H2, inert CSP for markup | `(.html and not ends_with("/index.html")) or .htm or .xhtml or .svg or .xml` | **only the `.svg` and `.xml` disjuncts verified.** The `.html` conjunct — the fiddly half, because it is the one carrying the exclusion — has nothing to test against until **M3.7** adds an `.html` fixture |
| H3, site CSP on pages | `(not contains ".") or ends_with("/index.html")` | **entirely unverified**; the first extensionless key and the first `index.html` arrive with **M4.1** |

Both rules that carry the `/index.html` exclusion have that exclusion untested, and for the same reason: it only fires on an object M4.1 creates. **Verify each branch against its first published object, and record the result here** — a green SVG does not make "the markup rules" verified. **M4.1 (ADR-032): verified 2026-09-16, deploy run `35056944994`.** `upload --site` wrote 133 keys, the purge covered 228 files, and `verify-live --mode smoke --site-dir build/site` passed `checked=189, failing=0`. That run checks H3 on `/`, on a format page with and without its slash and on both legal pages, H1's `/index.html` exclusion (no fixture headers on `/`), and H1 on a per-format index — so all three branches are now exercised by published objects.

**Where the bytes come from.** `--carry-forward <dir>` is the second gate's other half. The deploy resolves the pull request that produced the merge commit, finds that pull request's successful `ci.yml` run, and downloads its `carry-forward-fixtures` artifact. **That lookup does not have to be trusted**: `upload --fixtures` hashes every byte it is about to publish against the manifest and refuses anything that does not match, so an artifact from the wrong run cannot pass and provenance is established by content rather than by a run id. A missing artifact is likewise not an error in that step — most merges carry no `expected_drift` fixture, and the gate, which knows which paths need one, is what decides whether the absence matters.

### 3.2b `infra.yml` — on demand (maintainer operations without local credentials)

```yaml
name: infra
on:
  workflow_dispatch:
    inputs:
      mode: { type: choice, options: [audit, apply, probe, restore, redact], default: audit }
      restore_archive_url: { type: string, default: "" }   # restore mode only; must start with https://github.com/kumarprabhashanand/loremfile/releases/download/ — the tool refuses any other origin
      restore_only: { type: string, default: "" }          # optional comma-separated paths
      redact_path: { type: string, default: "" }           # fixture path, redact mode only
permissions: { contents: write }                            # write only for redact (re-uploading release assets); other modes do not touch the repository
jobs:
  run:
    runs-on: ubuntu-latest
    environment: production
    container: { image: "ghcr.io/kumarprabhashanand/loremfile-toolchain@sha256:<DIGEST>" }
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

**As implemented (restore, M4.4):**
- **Restore is two modes.** `restore-dry-run` downloads, verifies and prints the plan, and writes nothing. `restore` writes, purges what it wrote, and verifies only those paths (`11` §7.6 applies lock rules and the site later).
- **The inputs** `restore_archive_url` and `restore_only` are space-separated. They reach the shell only through `env`, and are checked for shape before anything runs.
- **Redact is two modes:** `redact-dry-run` names the releases that would change; `redact` rewrites them (§10, ADR-031).

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
    container: { image: "ghcr.io/kumarprabhashanand/loremfile-toolchain@sha256:<DIGEST>" }
    timeout-minutes: 30
    env: { CLOUDFLARE_ANALYTICS_TOKEN: ${{ secrets.CLOUDFLARE_ANALYTICS_TOKEN }}, CLOUDFLARE_ACCOUNT_ID: ${{ vars.CLOUDFLARE_ACCOUNT_ID }}, CLOUDFLARE_ZONE_ID: ${{ vars.CLOUDFLARE_ZONE_ID }} }
    steps:
      - uses: actions/checkout@<SHA-v4>
      - run: pip install -e . --no-deps
      - run: loremfile site build                       # deterministic for a given commit; its hashes are the site-integrity baseline (never read from the bucket)
      - id: verify
        run: loremfile verify-live --mode full --json ${{ inputs.inject_failure != '' && format('--inject-failure {0}', inputs.inject_failure) || '' }} > health.json || echo "failed=true" >> "$GITHUB_OUTPUT"
      - name: Open or update issue on failure, close on recovery
        env: { GH_TOKEN: ${{ github.token }} }
        run: python -m loremfile.gh_issue --label health --title "Health check failing" --report health.json --state ${{ steps.verify.outputs.failed == 'true' && 'failing' || 'ok' }}
      - name: Usage and cost check (R2 operations month-to-date, zone requests, hit ratio)
        env: { GH_TOKEN: ${{ github.token }} }
        run: loremfile usage --json > usage.json && python -m loremfile.gh_issue --label cost --title "R2 operations above threshold" --report usage.json --state $(python -c "import json;print('failing' if json.load(open('usage.json'))['summary']['r2_class_b_mtd']>5_000_000 else 'ok')")
      - name: Token rotation reminder (30 days before any expiry recorded in infra/token-expiry.json)
        env: { GH_TOKEN: ${{ github.token }} }
        run: loremfile tokens-due --json > tokens.json && python -m loremfile.gh_issue --label rotation-due --title "Token rotation due" --report tokens.json --state $(python -c "import json;print('failing' if json.load(open('tokens.json'))['summary']['due']>0 else 'ok')")
      - name: Weekly ops-log commit (Mondays) on the unprotected ops-log branch — backfills a row per day; also keeps scheduled workflows alive
        if: github.event_name == 'schedule'
        run: |
          # In a separate worktree. This listing used to check `ops-log` out in place, which
          # removes src/ — the editable install the next line imports — so it could never run.
          [ "$(date -u +%u)" = "1" ] || exit 0
          LOG="$RUNNER_TEMP/ops-log-worktree"
          git config --global --add safe.directory "$GITHUB_WORKSPACE"
          git config --global --add safe.directory "$LOG"
          git fetch origin +refs/heads/ops-log:refs/remotes/origin/ops-log 2>/dev/null || true
          if git show-ref --verify --quiet refs/remotes/origin/ops-log; then git worktree add -B ops-log "$LOG" origin/ops-log
          else git worktree add --detach "$LOG" HEAD && git -C "$LOG" checkout --orphan ops-log && git -C "$LOG" rm -rfq . ; fi
          python -m loremfile.ops_log --from usage.json --append "$LOG/ops-log.md"
          git -C "$LOG" add ops-log.md
          git -C "$LOG" diff --cached --quiet || { git -C "$LOG" -c user.name=loremfile-bot -c user.email=bot@loremfile.dev commit -qm "ops-log: weekly numbers" && git -C "$LOG" push origin ops-log; }
      - name: Fail the run if any check reported a problem   # must be last; why is in the table below
        if: ${{ !cancelled() }}
        run: '[ "${{ steps.verify.outputs.failed }}" != "true" ] && [ "${{ steps.cost.outputs.state }}" != "failing" ] && [ "${{ steps.rotation.outputs.state }}" != "failing" ]'
```

`loremfile usage` queries the GraphQL Analytics API (`r2OperationsAdaptiveGroups` for Class A/B operations month-to-date on the bucket; zone HTTP request totals and cache-status breakdown for the last 7 days) with the read-only T4 token. It **also** returns a `daily` array — per-day Class A, Class B and `GetObject`/`userError` counts for the last `--daily-days` days, default 32, which is the API's own maximum window (`19` §3.2). `ops_log` writes **one row per day** from that array and replaces any date already present, so the weekly commit backfills the week and overlapping windows converge instead of double-counting. The month-to-date counters answer "are we near the threshold"; the daily series answers "what is the rate", which is the question the pre-launch baseline needs and which a cumulative counter cannot express. The series lives in the repository because Cloudflare keeps only 90 days of it. `verify-live` treats a 429 from our own rate limit as "retry after 10 s", not as a failure. The ops-log commit goes to the dedicated **`ops-log` branch**, which carries no ruleset, so `main` keeps its pull-request requirement and no bypass is granted to any workflow (rulesets bypass by actor, not by path — a bypass for the Actions app would have applied to every workflow). `GITHUB_TOKEN` with `contents: write` can push only to unprotected branches. GitHub's 60-day rule speaks of "repository activity"; a push to any branch is repository activity. Should the rule turn out to count only default-branch commits (**[VERIFY]** by observing the workflow still runs after the first quiet 60 days), the weekly session's merged PRs keep `main` active anyway and the runbook's re-enable step covers the rest. The ops-log is read at `https://github.com/kumarprabhashanand/loremfile/blob/ops-log/ops-log.md`.

**Implemented M4.4, and what it does not yet carry.** An intentionally absent step with no owner becomes a permanently absent one, so each is named with the milestone that adds it, the same way §3.2 does:

| Deferred | Why | Returns with |
|---|---|---|
| ~~`loremfile site build`~~ | — | ✅ **M4.1**, with the legal values |
| ~~the site-key half of `verify-live` (the **defacement** check)~~ | — | ✅ **M4.1**: `--site-dir build/site --site-retry-seconds 600`; an empty build is a finding, not a clean check |

Since M4.1 the daily run rebuilds the checked-out commit and compares every site key; a mismatch is re-checked once after 10 minutes, so a deploy still publishing is not a finding.

**Incident, 2026-09-11 → 09-14: the alerting path failed silently for four days.** Every scheduled run of this workflow — four of four — and the first run of `audit.yml` failed, and **no issue was opened**. `verify-live` passed each time; the next step, `gh_issue`, died on `gh issue list` with `fatal: detected dubious ownership in repository at '/__w/loremfile/loremfile'`. Without `--repo`, `gh` infers the repository from the git checkout, and inside a job container git refuses a checkout owned by the runner's uid. With the default implicit `success()`, every later step was then skipped: **the cost check, the rotation reminder and the ops-log keep-alive did not run once.** It was found by reading the run history. **The project's own alert is the issue, and none was opened** — which is the failure this machinery exists to prevent. (GitHub may also email a failure notice for scheduled runs to whoever last changed the schedule; that is outside the repository, is not verifiable from here, and is not something this project relies on.) What changed:

| Defect | Fix |
|---|---|
| `gh` inferred the repository from a checkout git refused | every `gh_issue` call passes `--repo $GITHUB_REPOSITORY`. Tested at the `subprocess.run` boundary: every earlier test replaced `_gh`, so the one function that failed was the one no test ran |
| one reporting failure skipped every independent check | `if: ${{ !cancelled() }}` on each independent step. *(Corrected 2026-09-14: this row said "the job still ends red". That holds only for a step that **crashes** — see the next row)* |
| **a check that found a problem ended the run green** — found by the first control drill: the injected failure opened old issue #53 and the run was a green tick. `verify` (`\|\| echo failed=true`), cost and rotation (`\|\| true`) each swallow their result so the others still run, and nothing failed the job afterwards | cost and rotation record `state` to `$GITHUB_OUTPUT` as `verify` records `failed`; a **final** step with `if: ${{ !cancelled() }}` exits 1 when any of the three reported failing. **It must be last**: before the two did-not-complete steps, its exit 1 would make `failure()` open "Health workflow did not complete" on every real finding, and the `success()`-gated close would never run |
| a hung `verify-live` would read as `ok` and **close** a real health issue | state is `ok` only if the step **completed and passed** (`steps.verify.outcome`) — a timeout kills the shell before `|| echo failed=true`, so the output alone cannot tell "passed" from "never finished" |
| `verify-live` unbounded within a 30-minute job | step-level `timeout-minutes: 10`, sized from the four measured CI runs (21–99 s) with the arithmetic in the workflow. The job timeout is **not** re-sized: the whole job has never completed |
| the ops-log step **could never have succeeded** | it checked out `ops-log` in place, removing `src/` — the editable install `python -m loremfile.ops_log` needs — one line before running it. This section's own YAML block above has the same shape. It now works in a separate `git worktree` |
| a missing or corrupt report crashed the reporter | `gh_issue` treats an unreadable report as "the check did not complete" and says so, never as success |
| a job could fail in ways no check reports | a final `if: failure()` step opens "Health workflow did not complete"; a `success()` step closes it |

**Not verifiable before merge, and verified after it instead.** The `production` environment is restricted to `main`, so the check job cannot run from a branch. After merging, three dispatches are the test, in order: `inject_failure` set to any manifest path (watch "Health check failing" **open**); a plain dispatch (watch it **close**); `force_ops_log: true` (watch the `ops-log` branch appear). REQ-27's `inject_failure` control existed from M4.3 and was never dispatched — had it been, this would have been found on day one. `force_ops_log` is new, because the Monday commit is gated on a scheduled run and could not otherwise be exercised on demand.

**Done 2026-09-14 — the first alerting control drill passed**, recorded in `11` §7.11: the injected failure opened old issue #53, the clean run closed it, and `force_ops_log` created the `ops-log` branch (`6f2bf9b`). It also exposed the green-on-finding defect in the table above, so the drill is re-run after that fix: the injected run must now end **red** while old issue #53 still opens and closes as before.

**Health runs `verify-live --mode full` since 2026-09-14.** `daily` never hashed a fixture of 1 MB or more (`12` §4); full closes that gap without adding sampling logic, and at a measured 2 min 12 s it fits the unchanged 10-minute step bound. The `daily` description below is kept as the definition of that mode, which remains available.

The cost and rotation thresholds are applied in the workflow rather than inside the commands, because a threshold belongs to the check and `usage`/`tokens-due` should stay plain readers.

*(The next paragraph specifies `daily` as designed; `12` §4 records what is implemented, and `health.yml` now runs `full`.)* `verify-live --mode daily` = HEAD every manifest path (parallel, 16 workers, rate ≤ 20 rps to stay under our own limit) comparing `Content-Length` and `Content-Type`; GET + SHA-256 for all fixtures < 1 MB and a rotating 5 % sample of larger ones (rotation = day-of-year modulo); full header contract on one fixture per format (the smallest P1 fixture of that format by bytes, ties broken by path order); the encoded-path and warm-cache CORS probes from `08` §6; every site key hashed against the **rebuild of the checked-out commit** in `build/site/` (defacement check — the baseline must never come from the bucket, because whoever holds T2 can rewrite any site key including any manifest stored there; a mismatch during the few minutes between a merge and its deploy is tolerated by retrying once after 10 minutes); discovery files; `www` redirect; RDAP expiry ≥ 45 days; TLS certificate expiry ≥ 14 days; `security.txt` `Expires` ≥ 30 days; total time reported. `gh_issue.py` de-duplicates by label + title, appends a comment per failing day, and closes with a comment on the first green run.

### 3.4 `audit.yml` — weekly (Mondays) and on demand

Runs `loremfile infra audit` (unreadable settings are warnings; opens/updates an `infra-drift` issue only on real differences) and, on the first Monday of each month, `loremfile build --all --audit` (opens/updates a `determinism` issue on drift). Uses the `production` environment for the T1 token because Cloudflare tokens cannot be split read/write per call; the job's steps never call apply.

**The crawler watch (added 2026-09-22).** A third job, `crawlers`, reads the AI-agent list at `ai-robots-txt/ai.robots.txt` and reports the agents that are neither blocked here — in the WAF rule or in robots.txt (`04` §6) — nor recorded in `infra/crawlers-seen.json` as already weighed. It opens, updates or closes **one** advisory issue (`security`, "New AI crawlers to weigh"). It holds no zone credentials, stays outside the `loremfile-zone` group, and **never edits a rule**: blocking an agent is a decision about the two pages that name the operator, so the report is where it stops.

- **A list that cannot be read is not a finding about crawlers.** `crawler-watch` exits 3, and the issue step is skipped entirely, so the advisory is left exactly as it was found — the same rule the drift issue follows (`11` §7.2). Reporting `ok` there would close a real advisory on a run that read nothing.
- **Exit 4 fails the job**: a committed rule expression is over Cloudflare's documented 4,096-character maximum, which means the rule "cannot be created or updated" — better caught here than by the next `infra apply` against the live zone. Every committed expression is checked, not only the one that grows.
- Seeded on 2026-09-22 with the 175 agents the list held then, so the first quiet week is quiet by construction rather than by luck. Answering an advisory means either adding the token (`04` §6's documentation rule applies) or adding the name to `crawlers-seen.json` — both are pull requests, and both are the owner's call (`11` §7.12).

**Implemented M4.4. "Never calls apply" is enforced in three places rather than trusted**, because the job holds a token that *can* write:

1. the client is constructed `read_only=True` and raises `ReadOnlyError` on any write method, before the request is even recorded;
2. a unit test walks `audit.py`'s AST for calls to `put`/`patch`/`post`/`delete` and names the offender;
3. no step in the workflow invokes `infra apply`.

**`audit` is not `apply --dry-run`.** They share `apply.compare_rules`, so a dry run reports `updated` only for a phase or topology that differs; until 2026-09-15 it reported `updated` for all five phases plus `tiered-cache` on every run. They still answer different questions. A dry run says what `apply` *would write*: a difference is `updated` and exits 0, so it opens no issue, and its client no-ops writes rather than refusing them. `infra audit` reports *state*: drift exits 1, an audit that could not run exits 2, a resource it cannot read is a warning, and its client raises on any write. It reads each deployed ruleset and compares **rule content**, dropping the fields Cloudflare assigns (`id`, `version`, `last_updated`; `ref` is ours and compared) and comparing only the fields the committed rule declares, **in order** — order is part of a ruleset's meaning. The consequence is stated rather than hidden: a field Cloudflare filled in on its own is invisible here. We own what we declare.

**First real run, 2026-09-14 (Monday schedule): the content comparison works.** 33 resources `ok` against the live zone — including all five ruleset phases reporting `N rule(s) match`, the same phases `apply` then reported as `updated` on every run — plus `tiered-cache` and `tls_1_3`. One `unreadable`: **`url-normalization`**, whose endpoint T1 cannot read. That is a permission warning, correctly not drift, and it opens no issue; URL normalization was verified behaviourally by M2.4's encoded-path probe. The run then died in `gh_issue` (the incident in §3.3). The could-not-run state is now `ok` **only** on an exit code of 0 or 1: keyed on `== '2'` alone, a job that failed before the audit produced any code would have closed an open could-not-run issue on a run that never looked at the zone.

A further guard covers the whole set: a unit test asserts `audit.CHECKS` covers exactly the resources `apply.STEPS` writes. An audit that silently skipped one would report a clean zone for a zone it never looked at, which is worse than reporting drift because it looks like good news.

**Serialised with every job that touches the zone (ADR-029, 2026-09-15).** old issue #58 was a race: this job read a ruleset phase at 22:44:46 while a deploy applied a fourth rule at 22:45:16, and reported drift that was a timing artefact. `deploy.yml`, `infra.yml` and this workflow's `infra` job now share the `loremfile-zone` group with `cancel-in-progress: false`; the `determinism` job and `health.yml` stay outside. GitHub's `queue` property would stop a pending run being replaced, but actionlint 1.7.12 rejects it, so it is not used and the leftover risk — a pending scheduled audit cancelled without opening an issue — is handled in `11` §7.2.

**First determinism audit on a rebuilt image, 2026-09-16 (run `35135699048`).** The image moved to `1d66d83d` because old PR #67 rebuilt it — `gh` now installs from a SHA-256-pinned release tarball instead of the apt repository — and M3.9's audit had run on `3ba29bb9`, so this was the first audit of the fixtures under the pinned image. It exited 0 and opened no `determinism` issue. **Its counts are unavailable:** `--json` sends the report to `determinism.json` and `_report_audit` suppresses its stderr block under that flag, so the log held a green tick and nothing else — an audit of 0 rows would have looked identical. The job now prints `regenerated`, `drifted` and `expected_drift`, fails when they are absent, and uploads the report; `tests/unit/test_audit_workflow.py` runs those steps rather than reading them.

`build --audit` exits non-zero on **real** drift only; `expected_drift` paths are reported in their own section and exit 0, so the five fixtures known not to reproduce off this fleet do not train anyone to close the issue unread (`06` §8).

**`expected_drift` counts the five flagged rows that did not reproduce on the audit's runner.** They are published, so the audit compares them; a non-zero value is expected behaviour, not a regression, and zero means all five reproduced. (Until they were published they were absent from `manifest.json`, `_report_audit` skipped them, and the count was structurally zero.)

### 3.5 `release.yml` — on tag `v*`

1. Checks out the tag; verifies `manifest.json.catalog_version` equals the tag.
2. Finds the previous release tag with `git describe --tags --abbrev=0 <tag>^` (none for `v1.1.0`, the first tag).
3. `loremfile release archive --since <previous tag>` (or `--snapshot` for the first release and for every 10th minor release): downloads the fixtures added since the previous release **from production** (not regenerated), verifies each against the manifest hash, and writes `fixtures-<from>-<to>.tar` (uncompressed; contents are already compressed or incompressible) plus `manifest.json`, `sha256sums.txt` and a `CHANGELOG` excerpt. Archives are split at 1.5 GB into `…part1.tar`, `…part2.tar` with a `parts.txt` listing the parts and their SHA-256, so every asset stays under GitHub's 2 GB limit.
4. `gh release create v<version> --notes-file …` with the assets attached (needs `permissions: contents: write`).

**As implemented (M4.4, 2026-09-15).**

- **No environment, and no secret.** `production` admits only `main`, so a job started by a tag could not read its secrets, and the release needs none. Members are fetched from `https://loremfile.dev` through `verify_live.fetch`, which retries only a 429 from our own rate limit. `GITHUB_TOKEN` creates the release. There are two jobs:
  - `release` runs on a pushed `v*` tag only, and is the one job with `contents: write`;
  - `rehearse` runs on dispatch and publishes nothing.
- **The previous release** is the highest `vX.Y.Z` tag reachable from the tagged commit whose version is below the one being released (`git tag --merged HEAD`). It is not `git describe --tags --abbrev=0 <tag>^`, for two reasons:
  - `describe` exits 128 both when no tag exists and when something is actually wrong, and "no previous tag" means a snapshot;
  - `<tag>^` does not exist on a root commit.

  Versions compare as numbers, so `v1.10.0` follows `v1.9.0`.
- **"Every 10th minor release"** is read as a minor version that is a multiple of ten with patch 0 (`v1.10.0`, `v1.20.0`). `--since` and `--snapshot` override the choice.
- **The notes** are CHANGELOG.md's `## [X.Y.Z]` section. A tag run fails **before downloading anything** if that section is missing or empty (§7); a rehearsal records the absence instead.
- **Assets:**
  - `fixtures-<since>-<tag>.partN.tar`, or `fixtures-snapshot-<tag>.partN.tar`;
  - `parts.txt`;
  - `manifest.json` — the tag's file, byte for byte;
  - `sha256sums.txt` — every active fixture, as in `04` §2, so deltas extracted together check with `--ignore-missing` (`11` §7.6);
  - `notes.md`.

  A patch release usually adds no fixtures, so its archive is empty and no part is attached. The output directory must start empty, because every file in it is attached.
- **Rehearse before the first tag.** Dispatch `release.yml` on `main` before tagging `v1.1.0` (M5.5). It fetches and verifies every published fixture, assembles the snapshot, and publishes nothing.

**The first rehearsal failed, and what it found (2026-09-15).** Run `34982012684` (old commit `d1c4f751c8`) stopped before any download: `git tag --merged HEAD failed: fatal: detected dubious ownership in repository at '/__w/loremfile/loremfile'`.
- **Cause.** `actions/checkout` marks the repository safe only in a temporary global git config for its own step. Its log says "Temporarily overriding HOME='/__w/_temp/…' before making global git config changes", while later steps run with `HOME=/github/home`. In a job container the checkout belongs to the runner's uid and git runs as root, so git refuses the repository.
  - The `release` job had the same gap, so the first tag run would have failed identically.
  - The unit tests could not catch it, because their scratch repositories belong to the user running them.
- **Why `deploy.yml`'s `infra changed` worked: by accident.** Its `manifest check` step calls `build.merge_base_manifest`, which runs `git config --global --add safe.directory` as a side effect, three steps before `infra changed` needs git.
- **Fix.** Every containerised job now trusts the checkout explicitly with `git config --global --add safe.directory "$GITHUB_WORKSPACE"`, before its first step that runs git. That covers both `release.yml` jobs, `deploy.yml`, and `ci.yml`'s lint job (`tools/check_lock.sh`).
  - `tests/unit/test_workflow_git.py` pins the rule for every containerised step that runs git — directly, or through `infra changed`, `release archive`, `build --new`, `manifest check`/`update`/`adopt` or `check_lock.sh`.
  - It also checks that command list against the code in `src/` and `tools/` that actually runs git.
- **Passed:** run `34985088713` (old commit `71d32d657f`) — snapshot `v1.0.0`, 161 members, 414,208,239 bytes, one part, notes missing. That is what that run did, against the manifest of the day. **The first real tag is `v1.1.0`** (`catalog_version` 1.1.0, and `release.check_tag` requires the two to match), and the snapshot to expect from it is **223 members, 526,137,760 bytes**.

### 3.6 `toolchain.yml` — on changes under `tools/`

Triggered by a push **to `main`** touching `tools/Dockerfile`, `tools/apt-versions.txt`, `tools/requirements.lock`, `tools/smoke.sh` or the workflow itself, and by `workflow_dispatch`. The branch filter is load-bearing: `paths` alone also matches a tag push, and this workflow published an image on both release tags, on `action-v1` and on a Dependabot branch before it was added (2026-09-23). Permissions are per job and least-privilege: the `build` job takes `contents: read, packages: write`; only `propose-digest-bump` takes `contents: write, pull-requests: write`.

`build` builds `tools/Dockerfile`, pushes to `ghcr.io/kumarprabhashanand/loremfile-toolchain:<git-sha>` (**no `latest` tag** — workflows reference the image by digest and a moving tag would be a mutable surface), then smoke-tests **the pushed digest**, not a local build:

1. `tools/smoke.sh` inside the image — asserts every apt version matches `tools/apt-versions.txt`, all twelve ffmpeg encoders are present, SQLite answers an FTS5 `MATCH`, 31 Python modules import, `zstandard` round-trips, and the four determinism environment variables are set. It exits non-zero on the first failure.
2. `pip install -e .` with the repository mounted, then `import loremfile` — the image deliberately does **not** contain the package (the repository is mounted at run time), so this proves the image can still host it.

**Corrected in M1.3:** an earlier draft of this section said the workflow writes `dpkg -l > tools/apt-versions.txt`. It must not. That file is the pinned *input* the Dockerfile installs from and `smoke.sh` checks against; having the build overwrite it would be circular and would silently launder a drifted version into the pin. The full inventory (`dpkg-query` of every package, plus `pip freeze` and the image reference) is uploaded as the `toolchain-provenance` artifact instead, and `apt-versions.txt` changes only in a reviewed pull request.

**Two things learned when this ran for the first time (M1.5), both verified:**

- **`gh pr create` needs a repository setting, not just a token permission.** The job failed with `GitHub Actions is not permitted to create or approve pull requests (createPullRequest)` even with `pull-requests: write`. The switch is `can_approve_pull_request_reviews` on `PUT /repos/{owner}/{repo}/actions/permissions/workflow` (Settings → Actions → General → "Allow GitHub Actions to create and approve pull requests"), which is **off** on a new repository. It was turned on; the job then opened the pull request on a re-run.
- **The image build is not reproducible, so every build produces a new digest.** Two builds of identical inputs — same `Dockerfile`, same `apt-versions.txt`, same `requirements.lock` — produced `sha256:a976bbbf…` and `sha256:3ba29bb9…`. The *contents* are identical: `dpkg-query -W` and `pip freeze`, sorted and hashed, match exactly across both images, which is the pins doing their job. The image digest is simply not a content hash of the inputs. Consequence: a digest-bump pull request appears after **every** push that touches a trigger path, which is the intended flow, and a digest is only ever adopted after the smoke test has passed against it.

One-time bootstrap ordering note: the first `propose-digest-bump` ran while `ci.yml` existed only on a feature branch, so its `sed` had no `ci.yml` on `main` to update and it proposed a `TOOLCHAIN_DIGEST` change alone. That would have left `main` with a digest that `tests/unit/test_workflows_pinned.py` flags as mismatched. It was resolved by folding the new digest into the pull request that introduces `ci.yml` and closing the automated one. Once both files are on `main` the `sed` updates them together and the situation cannot recur.

**A digest bump is never merged as routine automation (rule added M2).** A new image can shift the generated bytes of formats already catalogued, so a bump merged mid-M3 would make M3.9's `build --all --audit` report drift across every format at once, with no way to separate a real regression from the image change. Bumps are batched into **one deliberate pull request at the M3 → M4 boundary**, which bumps the digest *and* runs the audit in the same change so any drift is seen and adopted in one place.

Two further reasons the automated pull request cannot simply be merged: GitHub does not run workflows on pull requests opened with `GITHUB_TOKEN`, so **the branch carries no checks at all** — nothing has verified that the committed fixtures still reproduce under the new image — and the manifest step in the job is skipped when the fixtures are not present in the runner. Treat the automated pull request as a *notification that a new image exists*, not as a change ready to land.

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
- **Site** (`--site`): upload every file under `build/site/` with the content-type table (`html`→`text/html; charset=utf-8`, extensionless→`text/html; charset=utf-8`, `json`→`application/json`, `txt`→`text/plain; charset=utf-8`, `xml`→`application/xml`, `css`→`text/css; charset=utf-8`, `js`→`text/javascript; charset=utf-8`, `svg`→`image/svg+xml`, `png`→`image/png`, `schema/*.json`→`application/schema+json`) and cache-control per `02` §4. Skip unchanged (compare sha256 metadata) unless `--force-site`. **As implemented (M4.1):** pages are `{key}.html` under `build/site/`, because a page key is also a prefix (`docs`, `docs/faq`); `site.routes` holds the type and cache tables; the upload refuses any key under a lock prefix (ADR-032) and any leftover `%%IMPRINT_*%%` placeholder (`13` §3b).
- **Restore** (`--restore <archive> [--only …]`, `--from-dir <dir>`): `--restore` accepts only URLs under `https://github.com/kumarprabhashanand/loremfile/releases/download/` (or a local file); read fixtures from the release archive or directory, verify each against the manifest, upload where the live object is missing; where a live object exists with a different hash the overwrite is attempted and, under a bucket lock, refused by R2 — the tool reports each refusal explicitly and the owner must lift that prefix's lock rule first (same ceremony as a takedown, `11` §7.8). A hash-differing object under an intact lock should never exist.

  **As implemented (M4.4, 2026-09-15).**
  - **Sources.**
    - `--restore` is repeatable. Each value is a release archive part: `https://github.com/<repository>/releases/download/<tag>/<name>.tar` (the repository is `$GITHUB_REPOSITORY`), or a local `.tar`. Anything else from the network is refused before it is requested.
    - github.com answers an asset with a `302` to its asset host, which is followed.
    - `--from-dir` reads fixtures at their manifest paths, and refuses a path that resolves outside the directory.
  - **What is taken.** Only members that are **active** manifest paths whose bytes match the manifest's hash and length.
    - A mismatching member stops the restore.
    - A **tombstone is never restored**, even from an older archive that still holds it.
    - Other members are listed and ignored.
    - Members are written to numbered scratch files, so a member's name cannot choose where it lands.
  - **What is written.** A missing object is uploaded and a matching one is skipped. An object whose hash differs, or that has no `sha256` metadata, is **replaced** — attempted through `r2.try_put_fixture`, with every refusal reported and the lock to lift named.
    - Restore has its own actions (`upload`, `replace`, `skip`); a deploy's plan still has no overwrite.
    - No lock gate applies, because a fresh account applies its lock rules after the restore (`11` §7.6 step 4).
  - **After writing,** every written URL is purged (`purge_restored_urls`), so neither a cached 404 nor the replaced bytes shadow it.
  - **Refused outright:** an `--only` path that the sources do not hold verified, and sources that hold nothing restorable.
- `--dry-run` prints the plan without writing; every mode prints counts: uploaded/skipped/removed/failed and total bytes.

## 6. Cache purge (`loremfile purge --site`)

`POST /zones/{zone_id}/purge_cache` with `{"prefixes": ["loremfile.dev/docs/", "loremfile.dev/legal/", "loremfile.dev/assets/"]}` plus `{"files": [ ...absolute URLs... ]}` for the root, format pages (both `/pdf` and `/pdf/`), discovery files and per-format `index.json`, in batches of 100 operations (the Free-plan per-request maximum; purge by prefix, hostname and tag are available on all plans). Fixtures and `schema/` are never purged (immutable) except in the takedown flow, which purges the removed URL. **As implemented (ADR-032):** the files also cover `/formats`, `/changelog`, `/status`, `/docs` and `/legal` with and without the slash, `llms-full.txt`, `search-index.json`, the icons, `.well-known/security.txt`, and `/_formats/{format}.json` beside `/{format}/index.json`.

## 7. Release and versioning

- `catalog_version` is semver in `manifest.json` and `CHANGELOG.md`. **Minor** = fixtures added or removed (tombstoned); **patch** = descriptions, tags, notes, deprecation flags or site-only changes (`props`, `bytes`, `sha256`, `mime` never change); **major** = manifest schema or URL contract change (never removes anything).
- Tags `v1.2.0` are created by the maintainer after the deploy that introduced the fixtures is green; `release.yml` runs. **Before tagging, move the released entries out of `[Unreleased]` under `## [1.2.0]`**: the release notes are that section, and a tag without it fails before anything is downloaded.
- `CHANGELOG.md` follows Keep a Changelog and is written for people who use the files: **one short bullet per change a user would notice** — files added or removed, a change to the URL or manifest contract, a notable site feature. No site-copy tweaks, layout, legal-link placement, infrastructure, milestone codes or doc references; those belong in the pull request and the docs. Keep `## [Unreleased]` at the top, even when empty.

## 8. Pull request template (excerpt)

```
## What
- [ ] New fixtures (list paths)  - [ ] Site/docs  - [ ] Infra  - [ ] Toolchain

## Checklist
- [ ] `loremfile catalog validate` passes locally
- [ ] Every new fixture has description, tags, expect, size_class
- [ ] No third-party content, no real personal data, no private keys, no executables, no external entities (13-legal-and-policy.md §5)
- [ ] I did not modify any existing manifest entry (immutability)
- [ ] CHANGELOG: one short bullet if a user would notice the change, or nothing
```

## 9. AGENTS.md (checked into the repo root; instructions for coding agents)

Contains: the CLI commands, the immutability rule in bold, "never edit manifest.json by hand — run `loremfile manifest update` in the container and commit the result", "always run inside the toolchain image", "never commit secrets or generated binaries", the owner (`kumarprabhashanand`, Q-03), the PR checklist, and a pointer to `docs/15-implementation-plan.md` for task order.

## 10. Takedown support in the release flow (`loremfile release redact`)

A removed fixture must also disappear from public GitHub Release assets. `loremfile release redact --path <path>` downloads every release archive that contains the path (from `parts.txt`/archive indexes), rebuilds the archive without it, re-uploads with `gh release upload --clobber`, updates `parts.txt` and the release notes with a "redacted <path> on <date>" line, and keeps the tombstone in `sha256sums.txt`. Runs from `infra.yml` (mode `redact`, input `redact_path`) so it needs no local credentials beyond `GITHUB_TOKEN` (`contents: write`). **As implemented:** affected releases are found from their part names and each tag's manifest in git; parts are rebuilt from the released bytes, re-verified, and replaced; `sha256sums.txt` and `manifest.json` stay as released; immutable releases are refused (ADR-031).
