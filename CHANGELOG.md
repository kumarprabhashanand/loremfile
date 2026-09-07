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

### Changed

- `docs/13-legal-and-policy.md` §3 privacy notice rewritten and §3a "Compliance posture"
  added; §8 replaced with a per-regime posture table. The previous rationale — "no
  personal data is collected by us" — was wrong: IP addresses are personal data,
  Cloudflare is the processor and the owner is the controller.
