import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { createServer, TOOLS } from "../client-js/src/mcp.js";
import bundledWorker from "../build/mcp-worker/index.mjs";
import { createHandler } from "./mcp.mjs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const manifest = JSON.parse(read("manifest.json"));
const formats = JSON.parse(read("formats.json")).formats.map((row) => row.format);
const url = "https://mcp.loremfile.dev/mcp";
const pdfIndex = "https://loremfile.dev/pdf/index.json";
const compactIndex = "https://loremfile.dev/mcp-index.json";
const names = ["list_fixtures", "describe_fixture"];
const modernVersion = "2026-07-28";
const headers = {
  "Content-Type": "application/json",
  Accept: "application/json, text/event-stream",
};
const meta = {
  "io.modelcontextprotocol/protocolVersion": modernVersion,
  "io.modelcontextprotocol/clientCapabilities": {},
};

function start(tools = TOOLS) {
  return createHandler(tools, { name: "loremfile", version: "0.2.2" }, formats);
}

function post(handle, method, params = {}, extra = {}, id = 1) {
  return handle(new Request(url, {
    method: "POST",
    headers: { ...headers, ...extra },
    body: JSON.stringify({ jsonrpc: "2.0", method, params, id: id ?? undefined }),
  }));
}

async function rpc(handle, method, params) {
  const response = await post(handle, method, params);
  assert.equal(response.status, 200);
  return response.json();
}

async function call(handle, name, args) {
  return rpc(handle, "tools/call", { name, arguments: args });
}

function intercept(t, reply) {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (target, options) => {
    const parsed = new URL(target);
    assert.equal(parsed.origin, "https://loremfile.dev");
    const key = parsed.pathname.slice(1);
    const match = /^([a-z0-9]+)\/index\.json$/.exec(key);
    assert.ok(match || key === "mcp-index.json", `unexpected network read: ${target}`);
    assert.equal(options.redirect, "error");
    requests.push({ target, headers: options.headers });
    const body = match && !formats.includes(match[1])
      ? null
      : read(`build/site/${match ? `_formats/${match[1]}.json` : key}`);
    return reply?.(body, target, options.headers) ??
      new Response(body, { status: body === null ? 404 : 200 });
  });
  return requests;
}

test("the bundled HTTPS handler serves the original two definitions", async () => {
  const { result } = await rpc(bundledWorker.fetch, "tools/list");
  assert.deepEqual(result.tools.map((tool) => tool.name), names);
  assert.deepEqual(result.tools, TOOLS.filter((tool) => names.includes(tool.name)));
  const limit = result.tools[0].inputSchema.properties.limit;
  assert.equal(limit.default, 50);
  assert.equal(limit.maximum, 250);
  const refused = await call(bundledWorker.fetch, "verify_file", { path: "pdf/sample.pdf" });
  assert.equal(refused.error.code, -32602);
});

async function checkOpenWorld(t, tools) {
  const requests = intercept(t);
  const { result } = await rpc(start(tools), "tools/list");
  assert.deepEqual(result.tools.map((tool) => tool.name), names);
  for (const tool of result.tools) {
    requests.length = 0;
    const args = tool.name === "describe_fixture" ? { path: "pdf/minimal.pdf" } : { limit: 1 };
    const response = await call(start(tools), tool.name, args);
    assert.equal(response.result.isError, undefined, tool.name);
    assert.deepEqual(requests.map(({ target }) => target), [
      tool.name === "describe_fixture" ? pdfIndex : compactIndex,
    ]);
    assert.equal(tool.annotations.openWorldHint, true, `${tool.name} reads over the network`);
  }
}

test("every discovered tool that reads the network declares an open world", async (t) => {
  await checkOpenWorld(t, TOOLS);
});

for (const name of names) {
  test(`the open-world guard rejects a closed-world annotation on ${name}`, async (t) => {
    const changed = TOOLS.map((tool) => tool.name === name
      ? { ...tool, annotations: { ...tool.annotations, openWorldHint: false } }
      : tool);
    await assert.rejects(checkOpenWorld(t, changed), { message: new RegExp(`^${name} reads over the network`) });
  });
}

test("both transports give identical results and errors from the real catalog", async (t) => {
  const requests = intercept(t);
  const stdio = createServer({ load: async () => manifest });
  await stdio.handle({ jsonrpc: "2.0", id: 0, method: "initialize" });
  const cases = [
    ["list_fixtures", {}, [compactIndex]],
    ["list_fixtures", { tag: ["encrypted", "edge"], max_bytes: 10_000, limit: 5, offset: 1 }, [compactIndex]],
    ["list_fixtures", { format: "pdf", max_bytes: 100_000, limit: 1, offset: 1 }, [pdfIndex]],
    ["list_fixtures", { format: ["pdf", "pdf"], tag: "encrypted" }, [pdfIndex]],
    ["list_fixtures", { format: formats, limit: 250, offset: 250 }, [compactIndex]],
    ["list_fixtures", { format: "unknown-format", offset: 100_000 }, [compactIndex]],
    ["list_fixtures", { max_bytes: 0, format: [] }, [compactIndex]],
    ["list_fixtures", { limit: 251 }, []],
    ["list_fixtures", { tag: null }, []],
    ["describe_fixture", { path: "pdf/sample.pdf" }, [pdfIndex]],
    ["describe_fixture", { path: "jpg/cmyk-640x480.jpg" }, ["https://loremfile.dev/jpg/index.json"]],
    ["describe_fixture", { path: "hls/multi-bitrate/master.m3u8" }, ["https://loremfile.dev/hls/index.json"]],
    ["describe_fixture", { path: "unknown/missing" }, ["https://loremfile.dev/unknown/index.json"]],
    ["describe_fixture", { path: "../manifest.json" }, []],
    ["describe_fixture", {}, []],
  ];
  for (const [name, args, expected] of cases) {
    requests.length = 0;
    const remote = await call(start(), name, args);
    const local = await stdio.handle({
      jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args },
    });
    assert.deepEqual(remote, local, JSON.stringify({ name, args }));
    assert.deepEqual(requests.map(({ target }) => target), expected);
  }
});

test("warm results are reused, 304 keeps parsed rows, and a version change invalidates other indexes", async (t) => {
  let now = 0;
  let version = manifest.catalog_version;
  t.mock.method(Date, "now", () => now);
  const requests = intercept(t, (body, _target, requestHeaders) => {
    const etag = `"${version}"`;
    return requestHeaders["If-None-Match"] === etag
      ? new Response(null, { status: 304 })
      : new Response(body.replace(manifest.catalog_version, version), { headers: { etag } });
  });
  const handle = start();
  const list = (args) => call(handle, "list_fixtures", { limit: 1, ...args });
  const tagged = await list({ format: "pdf" });
  await list({});
  assert.deepEqual(await list({ format: "pdf" }), tagged);
  assert.deepEqual(requests.map(({ target }) => target), [pdfIndex, compactIndex]);
  now += 60_001;
  assert.deepEqual(await list({ format: "pdf" }), tagged);
  assert.deepEqual(requests.at(-1).headers, { "If-None-Match": `"${version}"` });
  version = "1.99.0";
  assert.equal((await list({})).result.structuredContent.catalog_version, version);
  assert.equal((await list({ format: "pdf" })).result.structuredContent.catalog_version, version);
  assert.deepEqual(requests.slice(-2), [
    { target: compactIndex, headers: { "If-None-Match": `"${manifest.catalog_version}"` } },
    { target: pdfIndex, headers: {} },
  ]);
});

test("an upstream error costs one attempt and the next request can succeed", async (t) => {
  let broken = true;
  const requests = intercept(t, () => broken ? new Response(null, { status: 503 }) : undefined);
  const handle = start();
  const failed = await call(handle, "list_fixtures", { limit: 1 });
  assert.equal(failed.result.isError, true);
  assert.equal(requests.length, 1);
  broken = false;
  assert.equal((await call(handle, "list_fixtures", { limit: 1 })).result.structuredContent.count, 1);
  assert.equal(requests.length, 2);
});

test("a legacy initialize, notification, list and call use four HTTPS requests without a session", async (t) => {
  const requests = intercept(t);
  // A fresh handler per request exercises the absence of session affinity.
  const responses = [
    await post(start(), "initialize", { protocolVersion: "2025-11-25" }),
    await post(start(), "notifications/initialized", {}, {}, null),
    await post(start(), "tools/list", {}, { "MCP-Protocol-Version": "2025-11-25" }, 2),
    await post(start(), "tools/call", {
      name: "list_fixtures", arguments: { format: "pdf" },
    }, { "MCP-Protocol-Version": "2025-11-25" }, 3),
  ];
  assert.deepEqual(responses.map(({ status }) => status), [200, 202, 200, 200]);
  for (const response of responses) {
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.get("set-cookie"), null);
    assert.equal(response.headers.get("mcp-session-id"), null);
    assert.equal(response.headers.get("access-control-allow-origin"), null);
  }
  assert.deepEqual(requests.map(({ target }) => target), [pdfIndex]);
});

test("modern discovery and calls are stateless and require matching metadata headers", async (t) => {
  const requests = intercept(t);
  const extra = (method) => ({ "MCP-Protocol-Version": modernVersion, "Mcp-Method": method });
  const discover = await post(start(), "server/discover", { _meta: meta }, extra("server/discover"));
  const { result } = await discover.json();
  assert.ok(result.supportedVersions.includes(modernVersion));
  assert.deepEqual(result.capabilities, { tools: {} });
  const listing = await post(start(), "tools/list", { _meta: meta }, extra("tools/list"), 2);
  assert.deepEqual((await listing.json()).result.tools.map((tool) => tool.name), names);
  const method = "tools/call";
  const params = { name: "list_fixtures", arguments: { format: "pdf" }, _meta: meta };
  const okay = await post(start(), method, params, { ...extra(method), "Mcp-Name": params.name }, 3);
  assert.equal((await okay.json()).result.resultType, "complete");
  assert.deepEqual(requests.map(({ target }) => target), [pdfIndex]);
  const mismatch = await post(start(), method, params, { ...extra(method), "Mcp-Name": "describe_fixture" });
  assert.equal(mismatch.status, 400);
  assert.equal((await mismatch.json()).error.code, -32020);
});

test("the HTTP boundary refuses other paths, cross-origin requests, SSE GET, and invalid bodies", async () => {
  const handle = start();
  const wrong = await handle(new Request("https://mcp.loremfile.dev/legal/privacy"));
  assert.equal(wrong.status, 404);
  const cors = await post(handle, "tools/list", {}, { Origin: "https://example.org" });
  assert.equal(cors.status, 403);
  const get = await handle(new Request(url));
  assert.equal(get.status, 405);
  assert.equal(get.headers.get("allow"), "POST");
  assert.equal((await handle(new Request(url, { method: "DELETE" }))).status, 405);
  assert.equal((await post(handle, "tools/list", {}, { Accept: "text/event-stream" })).status, 406);
  assert.equal((await post(handle, "tools/list", {}, { "Content-Type": "text/plain" })).status, 415);
  const malformed = await handle(new Request(url, { method: "POST", headers, body: "{" }));
  assert.equal(malformed.status, 400);
  assert.equal((await malformed.json()).error.code, -32700);
  const oversized = await handle(new Request(url, { method: "POST", headers, body: " ".repeat(65_537) }));
  assert.equal(oversized.status, 413);
});
