# loremfile.dev — Documentation Set

**What this is.** A complete, implementation-ready specification for **loremfile.dev**: a free, ad-free, hotlink-friendly CDN of CC0 placeholder and test-fixture files ("Lorem Picsum, but for every file type") for developers, QA engineers and AI coding agents.

**Who it is for.** A junior engineer, an intern, or a coding agent who has never seen this project. If you read the documents in order and follow the implementation plan, you can build, deploy and operate the service end to end without asking anyone anything except the questions listed in `18-open-questions.md`.

**Status.** Specification v1.0, written 2026-09-07. Nothing is built yet. The domain `loremfile.dev` was verified unregistered on 2026-09-06.

## Reading order

| # | Document | Read it when you need to… |
|---|----------|---------------------------|
| 00 | [Overview](00-overview.md) | Understand the goal, non-goals, personas, success metrics, vocabulary |
| 01 | [Requirements](01-requirements.md) | Know exactly what "done" means (numbered REQ-IDs with acceptance criteria) |
| 02 | [Architecture](02-architecture.md) | See how the pieces fit; why there is no server |
| 03 | [HTTP contract](03-http-contract.md) | Implement or test URLs, headers, caching, CORS, immutability |
| 04 | [Manifest & discovery](04-manifest-and-discovery.md) | Implement `manifest.json`, `sha256sums.txt`, `llms.txt`, sitemap, security.txt |
| 05 | [Fixture catalog](05-fixture-catalog.md) | Know every fixture to generate, its parameters and expected properties |
| 06 | [Generation pipeline](06-generation-pipeline.md) | Write the generators, validators, lock check and toolchain container |
| 07 | [Website](07-website.md) | Build the static documentation site and its SEO |
| 08 | [Infrastructure](08-infrastructure.md) | Set up Cloudflare (Registrar, R2, rules, DNS) and the desired-state scripts |
| 09 | [CI/CD](09-ci-cd.md) | Set up the GitHub repository, workflows, secrets and releases |
| 10 | [Security](10-security.md) | Understand the threat model and every control |
| 11 | [Operations runbook](11-operations-runbook.md) | Run the weekly checklist or handle an incident |
| 12 | [Testing & QA](12-testing.md) | Know what tests exist, how to run them, the definition of done |
| 13 | [Legal & policy](13-legal-and-policy.md) | Licenses, terms, privacy, content rules, takedown |
| 14 | [Roadmap & extensions](14-roadmap-and-extensions.md) | Build phases 2–4 (edge cases, Worker endpoints, MCP server, unsafe fixtures) |
| 15 | [Implementation plan](15-implementation-plan.md) | Execute: milestones, ordered tasks, per-task definition of done |
| 16 | [Decisions (ADRs)](16-decisions.md) | Understand why each significant choice was made and what it rules out |
| 17 | [Risk register](17-risks.md) | Know what can go wrong and the mitigation for each |
| 18 | [Open questions](18-open-questions.md) | See the decisions only the owner can make, with the defaults assumed |
| 19 | [Cost & quotas](19-cost-and-quotas.md) | Know every quota, cost and alert threshold |

## Conventions used in these documents

- **MUST / SHOULD / MAY** are used as in RFC 2119.
- `loremfile.dev` is the production host. It is configurable (see `config.py` in `06-generation-pipeline.md`); every document uses the literal for readability.
- Placeholders in angle brackets are values you fill in: `<OWNER>` (GitHub user or org), `<ACCOUNT_ID>` (Cloudflare account ID), `<ZONE_ID>` (Cloudflare zone ID), `<BUCKET>` (R2 bucket name, default `loremfile-public`).
- Identifiers: `REQ-nn` requirement, `ADR-nnn` decision, `RISK-nn` risk, `Mn.n` milestone task, `Q-nn` open question. Cross-references use these IDs.
- All facts about third-party services (Cloudflare plan limits, prices, API shapes) were verified against the vendors' documentation on 2026-09-06/07. Where a fact could not be verified it is marked **[VERIFY]** and the implementation plan includes a task to verify it before relying on it.
- Byte sizes: `kb`, `mb`, `gb` are decimal (1 MB = 1,000,000 bytes). `kib`, `mib`, `gib` are binary (1 MiB = 1,048,576 bytes). This convention appears in fixture names and is enforced by the validators.

## Repository layout this documentation assumes

```
loremfile/                      # public GitHub repository <OWNER>/loremfile
├── README.md                   # short public readme (not this file)
├── AGENTS.md                   # instructions for coding agents working in the repo
├── LICENSE                     # MIT, covers code
├── LICENSES/CC0-1.0.txt        # covers generated fixtures
├── SECURITY.md  CONTRIBUTING.md  CHANGELOG.md  CODEOWNERS
├── .github/
│   ├── workflows/  ci.yml  deploy.yml  infra.yml  health.yml  audit.yml  release.yml  toolchain.yml
│   ├── ISSUE_TEMPLATE/  fixture-request.yml  bug.yml  config.yml
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── dependabot.yml
├── catalog/                    # declarative fixture definitions, one YAML per format
├── manifest.json               # generated lock file: one entry per published fixture (committed)
├── sha256sums.txt              # generated from manifest.json (committed)
├── src/loremfile/              # Python package: generators, validators, site builder, uploader, infra
├── infra/                      # Cloudflare desired state (JSON: zone settings, rulesets, CORS, bucket locks, DNS, token expiry dates)
├── site/                       # Jinja2 templates + static assets for the website
├── tests/                      # pytest suites
├── tools/                      # Dockerfile for the pinned toolchain; requirements files
├── THIRD_PARTY.md              # tools and libraries used to generate fixtures, with licences
└── docs/                       # this documentation set (00–19) plus launch/ (post drafts); weekly numbers live in ops-log.md on the unprotected `ops-log` branch
```

## Placeholders you must fill in

`<OWNER>` (GitHub owner), the contact mailbox, `<ACCOUNT_ID>` and `<ZONE_ID>` appear in `config.py`, the workflows, `security.txt`, `llms.txt` and the legal pages. M1 and M3 can be built with the placeholders in place; replace them with `grep -rn '<OWNER>'` before M2 (infrastructure) and M5 (first deploy). The open questions that decide them are Q-03 and Q-07 in `18-open-questions.md`.
