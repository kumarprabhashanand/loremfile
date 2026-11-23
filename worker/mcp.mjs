import {
  ToolError,
  describePath,
  describeResult,
  listArguments,
  listResult,
} from "../client-js/src/mcp-fixtures.mjs";
import { BASE_URL, IndexError, createCatalog } from "./catalog.mjs";

const ORIGIN = "https://mcp.loremfile.dev";
const LEGACY = "2025-11-25";
const MODERN = "2026-07-28";
const SUPPORTED = [MODERN, LEGACY];
const META = "io.modelcontextprotocol/";
const INSTRUCTIONS = "Find and describe CC0 fixtures at stable URLs from loremfile.dev.";
const MAX_BODY_BYTES = 64 * 1024;
const HEADERS = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const CACHE_HINT = { ttlMs: 3_600_000, cacheScope: "public" };

function rpcError(id, code, message, status = 200, data) {
  const error = { code, message };
  if (data !== undefined) {
    error.data = data;
  }
  return Response.json({ jsonrpc: "2.0", id, error }, { status, headers: HEADERS });
}

function empty(status, headers = {}) {
  return new Response(null, { status, headers: { ...HEADERS, ...headers } });
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function acceptsJSON(value) {
  return (value ?? "*/*").split(",").some((range) => {
    const [type, ...parameters] = range.trim().toLowerCase().split(";");
    return ["application/json", "application/*", "*/*"].includes(type.trim()) &&
      !parameters.some((parameter) => /^q\s*=\s*0(?:\.0*)?$/.test(parameter.trim()));
  });
}

async function readMessage(request) {
  if (Number(request.headers.get("Content-Length")) > MAX_BODY_BYTES) {
    return { status: 413 };
  }
  const reader = request.body?.getReader();
  if (!reader) {
    return { status: 400 };
  }
  let length = 0;
  let text = "";
  const decoder = new TextDecoder("utf-8", { fatal: true });
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        return { message: JSON.parse(text + decoder.decode()) };
      }
      length += value.byteLength;
      if (length > MAX_BODY_BYTES) {
        await reader.cancel();
        return { status: 413 };
      }
      text += decoder.decode(value, { stream: true });
    }
  } catch {
    return { status: 400 };
  } finally {
    reader.releaseLock();
  }
}

export function createHandler(toolDefinitions, serverInfo) {
  const handlers = new Map([
    ["list_fixtures", async (args) => {
      const query = listArguments(args);
      const { version, entries } = await loadCatalog();
      return listResult(entries, query, version, BASE_URL, (entry) => entry.isAlias);
    }],
    ["describe_fixture", async (args) => {
      const path = describePath(args);
      const { version, describe } = await loadCatalog();
      return describeResult(describe(path), version, BASE_URL);
    }],
  ]);
  const tools = toolDefinitions.filter((tool) => handlers.has(tool.name));
  const loadCatalog = createCatalog();

  function success(id, result, modern) {
    const payload = modern
      ? { resultType: "complete", ...result, _meta: { [`${META}serverInfo`]: serverInfo } }
      : result;
    return Response.json({ jsonrpc: "2.0", id, result: payload }, { headers: HEADERS });
  }

  async function callTool(id, params, modern) {
    if (typeof params?.name !== "string") {
      return rpcError(id, -32602, "tools/call needs a tool name");
    }
    const handler = handlers.get(params.name);
    if (handler === undefined) {
      return rpcError(id, -32602, `Unknown tool: ${params.name}`);
    }
    try {
      const structured = await handler(params.arguments ?? {});
      return success(id, {
        content: [{ type: "text", text: JSON.stringify(structured) }],
        structuredContent: structured,
      }, modern);
    } catch (error) {
      if (error instanceof ToolError || error instanceof IndexError) {
        const prefix = error instanceof IndexError ? "loremfile.dev could not be read: " : "";
        return success(id, {
          content: [{ type: "text", text: prefix + error.message }],
          isError: true,
        }, modern);
      }
      return rpcError(id, -32603, "Internal error", 500);
    }
  }

  return async function handle(request) {
    const { origin, pathname } = new URL(request.url);
    if (origin !== ORIGIN || pathname !== "/mcp") {
      return empty(404);
    }
    const caller = request.headers.get("Origin");
    if (caller !== null && caller !== ORIGIN) {
      return empty(403);
    }
    if (request.method !== "POST") {
      return empty(405, { Allow: "POST" });
    }
    if (request.headers.get("Content-Type")?.split(";", 1)[0].trim().toLowerCase() !== "application/json") {
      return empty(415);
    }
    if (!acceptsJSON(request.headers.get("Accept"))) {
      return empty(406);
    }
    const { message, status } = await readMessage(request);
    if (status === 413) {
      return empty(status);
    }
    if (status === 400) {
      return rpcError(null, -32700, "Parse error", status);
    }
    const id = message?.id;
    const notification = isObject(message) && !Object.hasOwn(message, "id");
    const validId = typeof id === "string" || Number.isInteger(id);
    if (message?.jsonrpc !== "2.0" || typeof message.method !== "string" ||
        !isObject(message) || (!notification && !validId)) {
      return rpcError(validId ? id : null, -32600, "not a JSON-RPC 2.0 request", 400);
    }
    const { method, params } = message;
    const headerVersion = request.headers.get("MCP-Protocol-Version");
    const version = params?._meta?.[`${META}protocolVersion`];
    const requested = version !== undefined && !SUPPORTED.includes(version)
      ? version
      : headerVersion ?? version;
    if (requested !== undefined && !SUPPORTED.includes(requested)) {
      return rpcError(id ?? null, -32022, "Unsupported protocol version", 400, {
        supported: SUPPORTED,
        requested,
      });
    }
    const modern = headerVersion === MODERN || version === MODERN;
    if (modern) {
      const toolName = request.headers.get("Mcp-Name");
      if (headerVersion !== version || request.headers.get("Mcp-Method") !== method ||
          (method === "tools/call" && (toolName === null || decodeName(toolName) !== params?.name))) {
        return rpcError(id ?? null, -32020, "MCP request headers do not match the body", 400);
      }
      if (!isObject(params._meta[`${META}clientCapabilities`])) {
        return rpcError(id ?? null, -32602, "clientCapabilities is required in _meta", 400);
      }
    }
    if (notification) {
      return empty(202);
    }
    if (method === "tools/list") {
      return success(id, modern ? { tools, ...CACHE_HINT } : { tools }, modern);
    }
    if (method === "tools/call") {
      return callTool(id, params, modern);
    }
    if (method === "server/discover" && modern) {
      return success(id, {
        supportedVersions: SUPPORTED,
        capabilities: { tools: {} },
        instructions: INSTRUCTIONS,
        ...CACHE_HINT,
      }, true);
    }
    if (method === "initialize" && !modern) {
      return success(id, {
        protocolVersion: LEGACY,
        capabilities: { tools: {} },
        serverInfo,
        instructions: INSTRUCTIONS,
      }, false);
    }
    if (method === "ping" && !modern) {
      return success(id, {}, false);
    }
    return rpcError(id, -32601, `Method not found: ${method}`, modern ? 404 : 200);
  };
}

function decodeName(value) {
  if (value === null || !value.startsWith("=?base64?") || !value.endsWith("?=")) {
    return value;
  }
  try {
    const bytes = Uint8Array.from(atob(value.slice(9, -2)), (character) => character.charCodeAt(0));
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}
