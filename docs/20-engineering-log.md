# Engineering log

Platform facts this project verified by observation, not by documentation alone, and that a
maintainer needs before changing a workflow, a rule or a generator. Where a statement rests on
documentation only, it says so. Commits, pull requests and issues cited elsewhere as "old commit",
"old PR #N" or "old issue #N" predate the repository's recreation and no longer resolve.

## GitHub Actions

- Inside a job container, git refuses the checkout as "dubious ownership": `actions/checkout` adds
  `safe.directory` only to a temporary config for its own step. Every containerised step that runs
  git needs `git config --global --add safe.directory "$GITHUB_WORKSPACE"` first
  (`tests/unit/test_workflow_git.py`). For the same reason `gh` cannot infer the repository there,
  so every `gh` call passes `--repo`.
- `inputs.*` is empty on every event that carries no inputs, so `if: inputs.mode == …` is silently
  false on `push`. Resolve an input once, where it is defaulted.
- With the implicit `success()`, one failing step skips every later step; independent steps need
  `if: ${{ !cancelled() }}`.
- A concurrency group keeps one pending run, and a newer arrival replaces it: a replaced run's
  commit is never deployed by its own run. `queue` is documented by GitHub and rejected by
  actionlint 1.7.12.
- `GITHUB_TOKEN` cannot create or update files under `.github/workflows/`, and pull requests it
  opens run no workflows. `container.image: ${{ needs.setup.outputs.digest }}` works on
  GitHub-hosted runners; without `needs: setup` it resolves to an empty string and the job runs on
  the bare runner instead of failing.
- An environment restricted to `main` gives a job started by a tag or a branch none of its secrets.
- Artifact `retention-days` is clamped silently by repository limits; read `expires_at` off the
  artifact. `carry-forward-fixtures` keeps 90 days and every `ci.yml` run re-uploads it.
- A push that creates a branch counts every path as changed, so path-filtered workflows run on it.

## GitHub repository and packages

- Force-pushing does not remove old commits from `refs/pull/*`, from `/pull/N.diff` or from commit
  URLs; deleting the repository does.
- A container package outlives the deletion of its linked repository and stays public and
  pullable by digest.

## The toolchain image and generators

- `docker build` is not reproducible: identical inputs give a new digest with identical contents.
  Every rebuild is a new reference and needs a determinism audit.
- `libx264`, `libvpx` and `libopus` pick SIMD kernels from the CPU at run time, and no ffmpeg option
  reaches that choice: `-cpuflags 0` and `-cpuflags sse2` give identical bytes. The same commit on
  the same runner label produced different Opus and VP9 bytes on two runs, so media output depends
  on the CPU of a heterogeneous runner pool. CI is the authority; the reference is the toolchain
  digest **and** the runner label (`ubuntu-24.04`).
- openpyxl spools each worksheet to a temporary file and adds it with `ZipFile.write`, stamping it
  from the filesystem; only `util.zipnorm` makes xlsx stable. fastavro draws its sync marker in a C
  extension, below the layer the determinism guard patches.
- The HLS segmenter cuts only on keyframes and libx264's default GOP is 250 frames, so keyframes
  are forced at every segment boundary. MP4 muxer overhead is small enough that sized MP4s need no
  discount on the analytic bitrate.

## Cloudflare edge (Free plan)

- 10 active Transform Rules, shared across URL rewrites and header rules, and a 2-hour minimum
  edge TTL (both from Cloudflare's plan documentation). `edge_ttl.status_code_ttl` is in the
  rulesets schema and not plan-gated.
- 404s are cached: a non-zero `Age` on the first sample. The duration is not measured; 3 minutes is
  the documented default.
- `cf-cache-status` cannot answer cache-key questions, because edge nodes in one colo do not share
  a local cache. `Age` can: a non-zero `Age` on `?x=2` after `?x=1` proves the query string is not
  part of the key.
- The rate limit counts cache hits and enforces consistently once load reaches one counter. It
  counts per `(ip.src, cf.colo.id)`, so a client spread over N data centres gets about N times the
  budget, and it bounds sustained load, not short bursts.
- `http.user_agent` works in custom WAF rules on Free. In the response header phase,
  `http.request.uri.path` is the path after URL rewrites.
- With 0-RTT on, the API reports `tls_1_3` as `zrt`; desired state must say `zrt`, not `on`.

## Cloudflare API

- Ruleset entry points are written with a full `PUT`, which replaces every rule in the phase; the
  custom WAF phase is shared with dashboard incident rules, so it is written rule by rule and never
  with `PUT`. A token cannot be limited to reads on a per-call basis.
- A DNS `PATCH` is a partial update. TXT content comes back quoted or unquoted, so it is compared
  with one pair of surrounding quotes removed. The apex holds several TXT records; `_dmarc` must
  stay single-valued (RFC 7489).
- T1 cannot read URL normalization; the audit reports it as unreadable, not as drift.
- GraphQL Analytics keeps 90 days (`cannot request data older than 12w6d`) and answers at most
  32 days at once (`cannot request a time range wider than 4w4d`). In `r2OperationsAdaptiveGroups`,
  `actionType: GetObject` with `actionStatus: userError` is a GET for a missing key.
- R2 → Overview's Class B counter is not reachable from an API token.

## R2

- A GET for a missing key is recorded as a Class B operation: 1,000 unique missing paths produced
  exactly 1,000 `GetObject`/`userError` records, and the dashboard's consumption counter agreed.
  Whether such a record is billed, no API reports.
- Metadata set when a multipart upload is initiated reaches the response unchanged. A multipart
  object's ETag is `"<hex>-<parts>"`, not an MD5.
- Under a bucket lock rule a new object can be created, and overwriting or deleting it is refused.
- A listing returns ETags, not SHA-256s, so each published key is compared by `HEAD` and its
  `sha256` metadata.

## Tools

- `python -O` strips every `assert`; checks raise explicitly.
- `urllib.request.urlopen` follows redirects; a check about a redirect must not.
- `git describe` exits 128 both when there is no tag and when something is broken.
- With Docker Desktop's containerd image store, `docker save` of an image pulled by digest wrote an
  8 KB archive with no layers; after the same image was loaded from an archive it saved in full. An
  OCI layout copied blob by blob from the registry keeps the exact digest.
