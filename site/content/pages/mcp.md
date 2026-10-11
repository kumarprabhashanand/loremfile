loremfile runs as a Model Context Protocol server, so an agent can find a fixture, read its
URL and measured properties, and check a file it already has. It returns URLs and metadata,
never file bytes: the agent, or your test, fetches the URL. The server talks over stdio and
reads the manifest once per process from loremfile.dev.

## Configure your client

With Node, the [npm package](https://www.npmjs.com/package/loremfile) runs the server:

```json
{ "mcpServers": { "loremfile": { "command": "npx", "args": ["-y", "loremfile", "mcp"] } } }
```

With Python, `uvx` runs the [PyPI package](https://pypi.org/project/loremfile/) without an
install:

```json
{ "mcpServers": { "loremfile": { "command": "uvx", "args": ["loremfile", "mcp"] } } }
```

Both are the same server, tool for tool: the two packages ship one tool definition file. It
speaks protocol `2026-07-28` and `2025-11-25`, so clients of either era work.

## Tools

All three are read-only.

| Tool | Arguments | Returns |
|---|---|---|
| `list_fixtures` | `format`, `tag`, `max_bytes`, `limit`, `offset` | One page of published fixtures, each with `path`, `url`, `format`, `mime`, `bytes`, `tags` and `description`, plus `total` and `next_offset`. |
| `describe_fixture` | `path` | One fixture's manifest entry: `url`, `mime`, `bytes`, `sha256`, `size_class`, `tags`, `description`, `props` and `added_in`. |
| `verify_file` | `path`, `file` | Whether a local file is the published one: `ok`, `changed` or `missing`, with both hashes and sizes. The file is read to hash it and goes nowhere. |

## Registry

The server is listed in the
[MCP Registry](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.kumarprabhashanand/loremfile)
as `io.github.kumarprabhashanand/loremfile`, pointing at the npm and PyPI packages above.
Without an agent, the same files are a URL away: see [getting started](/docs/getting-started).
