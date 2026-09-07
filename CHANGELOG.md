# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the catalog version follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) as defined in
`docs/09-ci-cd.md` §7:

- **minor** — fixtures added or removed (tombstoned);
- **patch** — descriptions, tags, notes, deprecation flags or site-only changes
  (`props`, `bytes`, `sha256` and `mime` never change);
- **major** — a manifest schema or URL contract change. It never removes anything.

## [Unreleased]

### Added

- The specification (`docs/00`–`19`) and its three review passes (`review/`).
- Repository skeleton: packaging, licences, contributor and agent documentation,
  issue and pull request templates, Dependabot configuration (M1.1).
- Pinned toolchain image: `tools/Dockerfile`, `tools/apt-versions.txt`,
  `tools/requirements.in`, `tools/requirements.lock` (89 packages, hashed),
  `tools/smoke.sh` and `tools/licences.py` (M1.2).
- `.github/workflows/toolchain.yml` — builds the image, publishes it to GHCR, smoke-tests
  the pushed digest and uploads a provenance artifact; `tools/TOOLCHAIN_DIGEST` records
  the published reference (M1.3).
- `tests/unit/test_requirements_lock.py` — asserts the lock is installable under
  `pip install --require-hashes`.
- `src/loremfile/config.py`, `catalog.py`, `manifest.py`, `schema/manifest-v1.json`,
  `catalog/_tags.yaml` and `tools/check_lock.sh`; the `loremfile catalog validate` and
  `loremfile manifest check|update` commands (M1.6).
- `util/determinism.py`, `util/sizing.py`, `util/zipnorm.py`, `util/lorem.py`,
  `util/ffmpeg.py`, `datasets.py`, `generators/base.py`, the word lists, per-script
  character inventories and the emoji list (M1.7).

### Fixed

- The catalog loader appended `; charset=utf-8` only to `text/*`. `docs/06` §6 also
  requires it for `application/json`, `application/xml`, `application/yaml`,
  `application/toml`, `application/x-ndjson` and `application/geo+json`.
- `util/ffmpeg.run` placed output-only options before the input, which is invalid
  ffmpeg argument grammar and failed outright with `-f lavfi`.

- `tools/requirements.lock` left `pip` and `setuptools` unpinned, so the toolchain image
  could not be built at all (`pip install --require-hashes` refused it). Regenerated with
  `--allow-unsafe`; a unit test now checks the file itself.

### Added — data formats (M3.2a)

- `csv/` (8), `tsv/` (1), `json/` (6), `ndjson/` (1), `xml/` (3), `yaml/` (1),
  `toml/` (1), `sql/` (1) — 22 launch fixtures, all serialising the shared `people`
  dataset so the same record can be compared across formats.
- `generators/data.py`, `validators/data.py`.

### Added — first fixtures

- `bin/` (23 fixtures, 230,715,033 bytes) and the text formats `txt/`, `md/`, `log/`,
  `ini/` (20 fixtures): generators, validators, catalogs, and the first `manifest.json`,
  `sha256sums.txt` and `formats.json` (M3.1).
- `loremfile build` and `loremfile validate`; the `build-and-validate` CI job.

### Changed

- **Q-22 resolved: `bin/100mib.bin` is phase 2, and the launch set is 228 fixtures, not
  229.** At 104,857,600 bytes it exceeded REQ-23's 100,000,000-byte cap while being
  listed phase 1. Deferred rather than excepted — nothing gets an exception at launch.
  Phase-1 total 417 → 416; P1b stays 188. `docs/05` §3.10's phase-2 note now states the
  real reason on all three deferred rows instead of "storage budget".

- `docs/13-legal-and-policy.md` §3 privacy notice rewritten and §3a "Compliance posture"
  added; §8 replaced with a per-regime posture table. The previous rationale — "no
  personal data is collected by us" — was wrong: IP addresses are personal data,
  Cloudflare is the processor and the owner is the controller.
- `docs/06-generation-pipeline.md` §9: the three M1.2 `[VERIFY]` items resolved against
  the built image — ffmpeg encoders (including `libx265` and `libsvtav1`), SQLite FTS5,
  and the absence of a zstd mode in Python 3.12's `tarfile`.
- `THIRD_PARTY.md`: the Python-libraries table filled in from installed package metadata,
  with a note on the three copyleft dependencies.
