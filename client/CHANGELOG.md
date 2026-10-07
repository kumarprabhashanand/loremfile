# Changelog

All notable changes to the `loremfile` client. The files it downloads have their own
versions, published at <https://loremfile.dev/changelog> — a catalog version says what is
on the service, this one says what the client does.

## [0.2.0] - 2026-10-07

- `loremfile mcp`: an MCP server on stdio with three read-only tools, `list_fixtures`, `describe_fixture` and `verify_file`, the same as the npm package's. It returns URLs and metadata, never file bytes, and speaks protocol 2026-07-28 and 2025-11-25; `uvx loremfile mcp` runs it without an install.

## [0.1.1] - 2026-10-01

- `verify` hashes a file a megabyte at a time instead of reading all of it into memory.
- `LOREMFILE_BASE_URL` checks the parsed host, so `http://127.0.0.1:1@other.host/` is refused.

## [0.1.0] - 2026-09-28

- First release: `loremfile get`, `list` and `verify`, every download checked against the
  published SHA-256 before it is written.
- Standard library only, Python 3.11 to 3.14, on Linux, macOS and Windows.
