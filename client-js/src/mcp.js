// `loremfile mcp`: a Model Context Protocol server on stdio (modelcontextprotocol.io).
//
// Dual-era, as the 2026-07-28 specification permits. A request that carries
// `io.modelcontextprotocol/protocolVersion` in `_meta` is served on its own, with no session;
// an `initialize` request opens the 2025-11-25 session older clients expect. One message per
// line in each direction, and nothing else is ever written to stdout.
//
// Node built-ins only, like the rest of the package: no SDK. The tools return URLs and
// metadata and never a file's bytes — the agent, or the test it is writing, fetches the URL.

import { readFileSync } from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";

import * as api from "./api.js";

export const MODERN = "2026-07-28";
export const LEGACY = "2025-11-25";
/** Newest first: what `server/discover` and a version error advertise. */
export const SUPPORTED = [MODERN, LEGACY];

const META = "io.modelcontextprotocol/";
export const DEFAULT_LIMIT = 50;
export const MAX_LIMIT = 250;

/** JSON-RPC codes, and the one MCP code this server uses. */
export const CODES = {
  PARSE: -32700,
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
  INTERNAL: -32603,
  UNSUPPORTED_VERSION: -32022,
};

export const SERVER_INFO = {
  name: "loremfile",
  version: JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")).version,
};

const INSTRUCTIONS =
  "CC0 sample files and test fixtures from loremfile.dev, each at a stable URL. Use " +
  "list_fixtures to find one, describe_fixture for its size, hash and measured properties, " +
  "and verify_file to check a copy on disk. The tools return URLs, never file contents.";

const READ_ONLY = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  // One host and one published list, not an open world.
  openWorldHint: false,
};

const STRINGS = {
  anyOf: [{ type: "string" }, { type: "array", items: { type: "string" } }],
};
const NULLABLE_STRING = { type: ["string", "null"] };
const NULLABLE_INTEGER = { type: ["integer", "null"] };

const LISTED = {
  type: "object",
  properties: {
    path: { type: "string" },
    url: { type: "string" },
    format: { type: "string" },
    mime: { type: "string" },
    bytes: { type: "integer" },
    tags: { type: "array", items: { type: "string" } },
    description: { type: "string" },
  },
  required: ["path", "url", "format", "mime", "bytes", "tags", "description"],
};

/** The tool surface. client-js/README.md documents it, and a test holds the two together. */
export const TOOLS = [
  {
    name: "list_fixtures",
    title: "List loremfile.dev fixtures",
    description:
      "One page of the published sample files, filtered by format, tag and size. Each comes " +
      "with its URL and a description of what it is for. `total` counts every match and " +
      "`next_offset` fetches the next page; it is null on the last.",
    inputSchema: {
      type: "object",
      properties: {
        format: { ...STRINGS, description: 'Formats to include, any of, e.g. ["pdf", "png"].' },
        tag: { ...STRINGS, description: 'Tags to include, any of, e.g. ["encrypted"].' },
        max_bytes: { type: "integer", minimum: 0, description: "Only files of at most this size." },
        limit: {
          type: "integer",
          minimum: 1,
          maximum: MAX_LIMIT,
          default: DEFAULT_LIMIT,
          description: `Fixtures per page, ${DEFAULT_LIMIT} unless set, at most ${MAX_LIMIT}.`,
        },
        offset: { type: "integer", minimum: 0, default: 0, description: "Matches to skip." },
      },
      additionalProperties: false,
    },
    outputSchema: {
      type: "object",
      properties: {
        catalog_version: { type: "string" },
        total: { type: "integer" },
        offset: { type: "integer" },
        limit: { type: "integer" },
        count: { type: "integer" },
        next_offset: NULLABLE_INTEGER,
        fixtures: { type: "array", items: LISTED },
      },
      required: ["catalog_version", "total", "offset", "limit", "count", "next_offset", "fixtures"],
    },
    annotations: READ_ONLY,
  },
  {
    name: "describe_fixture",
    title: "Describe one loremfile.dev fixture",
    description:
      "The published manifest entry for one fixture: its URL, MIME type, size, SHA-256, tags, " +
      "description and measured properties. Metadata only; fetch the URL for the file.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: 'A fixture path, e.g. "pdf/minimal.pdf".' },
      },
      required: ["path"],
      additionalProperties: false,
    },
    outputSchema: {
      type: "object",
      properties: {
        catalog_version: { type: "string" },
        path: { type: "string" },
        url: { type: "string" },
        format: { type: "string" },
        mime: { type: "string" },
        bytes: { type: "integer" },
        sha256: { type: "string" },
        size_class: NULLABLE_STRING,
        tags: { type: "array", items: { type: "string" } },
        description: { type: "string" },
        props: { type: ["object", "null"] },
        added_in: NULLABLE_STRING,
      },
      required: [
        "catalog_version",
        "path",
        "url",
        "format",
        "mime",
        "bytes",
        "sha256",
        "size_class",
        "tags",
        "description",
        "props",
        "added_in",
      ],
    },
    annotations: READ_ONLY,
  },
  {
    name: "verify_file",
    title: "Verify a local copy of a loremfile.dev fixture",
    description:
      "Hash a file on this machine and compare it with the published SHA-256 and size of a " +
      "fixture. `status` is ok, changed or missing. The file is read only to hash it.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: 'The fixture path, e.g. "pdf/minimal.pdf".' },
        file: {
          type: "string",
          description: "The local file: absolute, or relative to where the server was started.",
        },
      },
      required: ["path", "file"],
      additionalProperties: false,
    },
    outputSchema: {
      type: "object",
      properties: {
        path: { type: "string" },
        file: { type: "string" },
        status: { type: "string", enum: ["ok", "changed", "missing"] },
        expected_sha256: { type: "string" },
        actual_sha256: NULLABLE_STRING,
        expected_bytes: { type: "integer" },
        actual_bytes: NULLABLE_INTEGER,
      },
      required: [
        "path",
        "file",
        "status",
        "expected_sha256",
        "actual_sha256",
        "expected_bytes",
        "actual_bytes",
      ],
    },
    annotations: READ_ONLY,
  },
];

/** A failure the model can act on: a tool result with `isError`, not a protocol error. */
export class ToolError extends Error {}

class ProtocolError extends Error {
  constructor(code, message, data) {
    super(message);
    this.code = code;
    this.data = data;
  }
}

// --- arguments ----------------------------------------------------------------------------

function only(args, allowed) {
  if (args === null || typeof args !== "object" || Array.isArray(args)) {
    throw new ToolError("arguments must be an object");
  }
  const unknown = Object.keys(args).filter((key) => !allowed.includes(key));
  if (unknown.length > 0) {
    throw new ToolError(
      `unknown argument ${unknown.join(", ")}; this tool takes ${allowed.join(", ")}`,
    );
  }
  return args;
}

function strings(value, name) {
  if (value === undefined) {
    return [];
  }
  const list = typeof value === "string" ? [value] : value;
  if (!Array.isArray(list) || !list.every((item) => typeof item === "string")) {
    throw new ToolError(`${name} must be a list of strings`);
  }
  return list;
}

function integer(value, name, { min, max, fallback }) {
  if (value === undefined) {
    return fallback;
  }
  if (!Number.isInteger(value) || value < min || (max !== undefined && value > max)) {
    const range = max === undefined ? `at least ${min}` : `from ${min} to ${max}`;
    throw new ToolError(`${name} must be a whole number ${range}, not ${JSON.stringify(value)}`);
  }
  return value;
}

function text(value, name) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new ToolError(`${name} is required and must be a non-empty string`);
  }
  return value;
}

// --- the tools ----------------------------------------------------------------------------

function url(entry) {
  return `${api.baseUrl()}${entry.path}`;
}

function byPath(document, fixturePath) {
  const entry = api.active(document).find((candidate) => candidate.path === fixturePath);
  if (entry === undefined) {
    throw new ToolError(
      `no published fixture at ${JSON.stringify(fixturePath)}; ` +
        "list_fixtures shows what is published",
    );
  }
  return entry;
}

async function listFixtures(document, args) {
  only(args, ["format", "tag", "max_bytes", "limit", "offset"]);
  const formats = strings(args.format, "format");
  const tags = strings(args.tag, "tag");
  const maxBytes = integer(args.max_bytes, "max_bytes", { min: 0, fallback: null });
  const limit = integer(args.limit, "limit", { min: 1, max: MAX_LIMIT, fallback: DEFAULT_LIMIT });
  const offset = integer(args.offset, "offset", { min: 0, fallback: 0 });
  // The same filters as `loremfile list`: any of the formats, any of the tags, all three kinds.
  const matches = api
    .active(document)
    .filter((e) => formats.length === 0 || formats.includes(e.format))
    .filter((e) => tags.length === 0 || (e.tags ?? []).some((tag) => tags.includes(tag)))
    .filter((e) => maxBytes === null || e.bytes <= maxBytes)
    .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  const page = matches.slice(offset, offset + limit);
  return {
    catalog_version: String(document.catalog_version ?? ""),
    total: matches.length,
    offset,
    limit,
    count: page.length,
    next_offset: offset + limit < matches.length ? offset + limit : null,
    fixtures: page.map((e) => ({
      path: e.path,
      url: url(e),
      format: e.format,
      mime: e.mime,
      bytes: e.bytes,
      tags: e.tags ?? [],
      description: e.description ?? "",
    })),
  };
}

async function describeFixture(document, args) {
  only(args, ["path"]);
  const entry = byPath(document, text(args.path, "path"));
  return {
    catalog_version: String(document.catalog_version ?? ""),
    path: entry.path,
    url: url(entry),
    format: entry.format,
    mime: entry.mime,
    bytes: entry.bytes,
    sha256: entry.sha256,
    size_class: entry.size_class ?? null,
    tags: entry.tags ?? [],
    description: entry.description ?? "",
    props: entry.props ?? null,
    added_in: entry.added_in ?? null,
  };
}

async function verifyFile(document, args) {
  only(args, ["path", "file"]);
  const entry = byPath(document, text(args.path, "path"));
  const file = path.resolve(text(args.file, "file"));
  const info = await api.fileInfo(file);
  const actual = info === null ? null : await api.hashFile(file);
  return {
    path: entry.path,
    file,
    status: info === null ? "missing" : actual === entry.sha256 ? "ok" : "changed",
    expected_sha256: entry.sha256,
    actual_sha256: actual,
    expected_bytes: entry.bytes,
    actual_bytes: info === null ? null : info.size,
  };
}

const HANDLERS = {
  list_fixtures: listFixtures,
  describe_fixture: describeFixture,
  verify_file: verifyFile,
};

// --- the protocol -------------------------------------------------------------------------

/**
 * One server's state: the manifest, read once, and the legacy session if a client opened one.
 * `load` exists so tests can count reads; it defaults to the client's own manifest fetch.
 */
export function createServer({ load = () => api.manifest() } = {}) {
  let manifest = null;
  let session = null; // the negotiated legacy version, once `initialize` arrives

  function published() {
    // Kept for the process; dropped on failure, so a later call can try again.
    manifest ??= load().catch((error) => {
      manifest = null;
      throw error;
    });
    return manifest;
  }

  async function callTool(params) {
    if (params === null || typeof params !== "object" || typeof params.name !== "string") {
      throw new ProtocolError(CODES.INVALID_PARAMS, "tools/call needs a tool name");
    }
    const handler = HANDLERS[params.name];
    if (handler === undefined) {
      throw new ProtocolError(CODES.INVALID_PARAMS, `Unknown tool: ${params.name}`);
    }
    try {
      const structured = await handler(await published(), params.arguments ?? {});
      return {
        content: [{ type: "text", text: JSON.stringify(structured) }],
        structuredContent: structured,
      };
    } catch (error) {
      if (
        error instanceof ToolError ||
        error instanceof api.Refused ||
        error instanceof api.Unreachable
      ) {
        const prefix = error instanceof api.Unreachable ? "loremfile.dev could not be read: " : "";
        return { content: [{ type: "text", text: `${prefix}${error.message}` }], isError: true };
      }
      throw error;
    }
  }

  async function dispatch(method, params, modern) {
    if (method === "tools/list") {
      return modern ? { tools: TOOLS, ttlMs: 3_600_000, cacheScope: "public" } : { tools: TOOLS };
    }
    if (method === "tools/call") {
      return callTool(params);
    }
    if (method === "server/discover" && modern) {
      return {
        supportedVersions: SUPPORTED,
        capabilities: { tools: {} },
        instructions: INSTRUCTIONS,
        ttlMs: 3_600_000,
        cacheScope: "public",
      };
    }
    if (method === "ping" && !modern) {
      return {};
    }
    throw new ProtocolError(CODES.METHOD_NOT_FOUND, `Method not found: ${method}`);
  }

  async function request(method, params) {
    if (method === "initialize") {
      // 2025-11-25 negotiation: echo a version this server speaks, otherwise offer its own.
      const asked = params?.protocolVersion;
      session = asked === LEGACY ? asked : LEGACY;
      return {
        protocolVersion: session,
        capabilities: { tools: {} },
        serverInfo: SERVER_INFO,
        instructions: INSTRUCTIONS,
      };
    }
    const meta = params?._meta;
    const version = meta?.[`${META}protocolVersion`];
    if (version !== undefined) {
      if (!SUPPORTED.includes(version)) {
        throw new ProtocolError(CODES.UNSUPPORTED_VERSION, "Unsupported protocol version", {
          supported: SUPPORTED,
          requested: version,
        });
      }
      const capabilities = meta[`${META}clientCapabilities`];
      if (
        capabilities === null ||
        typeof capabilities !== "object" ||
        Array.isArray(capabilities)
      ) {
        throw new ProtocolError(
          CODES.INVALID_PARAMS,
          `_meta lacks the required ${META}clientCapabilities`,
        );
      }
      const result = await dispatch(method, params, version === MODERN);
      if (version !== MODERN) {
        return result;
      }
      return { resultType: "complete", ...result, _meta: { [`${META}serverInfo`]: SERVER_INFO } };
    }
    if (session !== null || method === "ping") {
      return dispatch(method, params, false);
    }
    throw new ProtocolError(
      CODES.INVALID_PARAMS,
      `_meta lacks the required ${META}protocolVersion; send it on every request ` +
        `(protocol ${MODERN}) or open a session with initialize (protocol ${LEGACY})`,
    );
  }

  /** The reply to one parsed message, or null when there is nothing to send. */
  async function handle(message) {
    if (message === null || typeof message !== "object" || Array.isArray(message)) {
      return {
        jsonrpc: "2.0",
        error: { code: CODES.INVALID_REQUEST, message: "not a JSON-RPC object" },
      };
    }
    const hasId = Object.hasOwn(message, "id");
    if (!hasId) {
      return null; // a notification: initialized, cancelled; nothing to answer
    }
    const { id } = message;
    if (
      message.jsonrpc !== "2.0" ||
      typeof message.method !== "string" ||
      !(typeof id === "string" || Number.isInteger(id))
    ) {
      return {
        jsonrpc: "2.0",
        id,
        error: { code: CODES.INVALID_REQUEST, message: "not a JSON-RPC 2.0 request" },
      };
    }
    try {
      return { jsonrpc: "2.0", id, result: await request(message.method, message.params) };
    } catch (error) {
      if (error instanceof ProtocolError) {
        const body = { code: error.code, message: error.message };
        return {
          jsonrpc: "2.0",
          id,
          error: error.data === undefined ? body : { ...body, data: error.data },
        };
      }
      return {
        jsonrpc: "2.0",
        id,
        error: { code: CODES.INTERNAL, message: String(error?.message ?? error) },
      };
    }
  }

  /** The reply to one line of input, or null. */
  async function line(raw) {
    if (raw.trim() === "") {
      return null;
    }
    let message;
    try {
      message = JSON.parse(raw);
    } catch {
      return { jsonrpc: "2.0", error: { code: CODES.PARSE, message: "Parse error" } };
    }
    return handle(message);
  }

  return { handle, line };
}

/**
 * Serve until the input ends: one message per line in, one per line out, in order.
 * Resolves once every reply has been written, so the process can exit cleanly.
 */
export async function serve({
  input = process.stdin,
  write = (text) => process.stdout.write(text),
  server = createServer(),
} = {}) {
  const lines = createInterface({ input, crlfDelay: Infinity });
  let pending = Promise.resolve();
  for await (const raw of lines) {
    pending = pending.then(async () => {
      const reply = await server.line(raw);
      if (reply !== null) {
        write(`${JSON.stringify(reply)}\n`);
      }
    });
  }
  await pending;
}
