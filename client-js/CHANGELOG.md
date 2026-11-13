# Changelog

All notable changes to the `loremfile` npm package. The files it downloads have their own
versions, published at <https://loremfile.dev/changelog> — a catalog version says what is
on the service, this one says what the client does.

## [0.2.1]

- `get --format`, `list` and the MCP `list_fixtures` leave out the `sample.{format}` aliases, which repeat another file's bytes, so a format no longer arrives twice. `--include-aliases` brings them back; a path named outright is always fetched.

## [0.2.0]

- `loremfile mcp`: an MCP server on stdio with three read-only tools, `list_fixtures`, `describe_fixture` and `verify_file`. It returns URLs and metadata, never file bytes, and speaks protocol 2026-07-28 and 2025-11-25.

## [0.1.0]

- First release: `loremfile get`, `list` and `verify`, every download checked against its SHA-256 before it is written.
