# Security policy

## Reporting a vulnerability

Use GitHub **private vulnerability reporting** (Security → Report a vulnerability on
this repository) or email `security@loremfile.dev`.

You will get an acknowledgement **within 7 days**. This project has no on-call rota
and no bug bounty.

Please **do not run volumetric tests** against loremfile.dev. The service is free and
its whole cost model depends on not being hammered; if you want to test rate limiting,
tell us and we will discuss it.

## In scope

- Anything that lets a third party **change or remove** published content.
- Anything that lets a third party **execute script in the `loremfile.dev` origin**.
- Anything that **inflates costs** beyond what the documented rate limit intends.

## Out of scope

- Rate limiting itself.
- Missing headers on 404 pages.
- Findings that require a compromise of the Cloudflare account.

## What we will tell you

Fixed issues are described in `CHANGELOG.md`. If a fix changes a published file it will
be a **new path** — bytes at an existing path never change (see the immutability rule in
`README.md` and `docs/03-http-contract.md`).

The threat model and the full set of controls are in
[`docs/10-security.md`](docs/10-security.md).
