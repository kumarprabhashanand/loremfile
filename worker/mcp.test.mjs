import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { createServer, TOOLS } from "../client-js/src/mcp.js";
import bundledWorker from "../build/mcp-worker/index.mjs";
import { createHandler } from "./mcp.mjs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const manifest = JSON.parse(read("manifest.json"));
const formats = JSON.parse(read("formats.json")).formats.map((row) => row.format);
const index = read("build/site/mcp-index.json");
const smokeRequests = JSON.parse(read("build/mcp-worker/smoke-requests.json"));
const aliases = new Set(manifest.fixtures
  .filter((entry) => entry.generator === "alias.copy")
  .map((entry) => entry.path));
const smokeAlias = smokeRequests.find(([method, params]) =>
  method === "tools/call" && params.name === "describe_fixture" && aliases.has(params.arguments.path)
)?.[1].arguments.path;
const url = "https://mcp.loremfile.dev/mcp";
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
  return createHandler(tools, { name: "loremfile", version: "0.2.2" });
}

function post(handle, method, params = {}, extra = {}, id = 1) {
  return handle(new Request(url, {
    method: "POST",
    headers: { ...headers, ...extra },
    body: JSON.stringify({ jsonrpc: "2.0", method, params, id: id ?? undefined }),
  }));
}

async function rpc(handle, method, params, extra) {
  const response = await post(handle, method, params, extra);
  assert.equal(response.status, 200);
  return response.json();
}

async function call(handle, name, args) {
  return rpc(handle, "tools/call", { name, arguments: args });
}

function intercept(t, reply) {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (target, options) => {
    requests.push({ target, headers: options.headers });
    assert.equal(target, compactIndex);
    assert.equal(options.redirect, "error");
    return reply?.(index, target, options.headers) ?? new Response(index);
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
    assert.deepEqual(requests.map(({ target }) => target), [compactIndex]);
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
    ["list_fixtures", { format: "pdf", max_bytes: 100_000, limit: 1, offset: 1 }, [compactIndex]],
    ["list_fixtures", { format: ["pdf", "pdf"], tag: "encrypted" }, [compactIndex]],
    ["list_fixtures", { format: formats, limit: 250, offset: 250 }, [compactIndex]],
    ["list_fixtures", { format: "unknown-format", offset: 100_000 }, [compactIndex]],
    ["list_fixtures", { max_bytes: 0, format: [] }, [compactIndex]],
    ["list_fixtures", { limit: 251 }, []],
    ["list_fixtures", { tag: null }, []],
    ["describe_fixture", { path: "jpg/cmyk-640x480.jpg" }, [compactIndex]],
    ["describe_fixture", { path: "hls/multi-bitrate/master.m3u8" }, [compactIndex]],
    ["describe_fixture", { path: "edge/zero-byte.zip" }, [compactIndex]],
    ["describe_fixture", { path: "unknown/missing" }, [compactIndex]],
    ["describe_fixture", { path: "../manifest.json" }, [compactIndex]],
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

async function checkSmokeParity(handle) {
  const stdio = createServer({ load: async () => manifest });
  await stdio.handle({ jsonrpc: "2.0", id: 0, method: "initialize" });
  assert.ok(smokeAlias, "control: smoke describes a published alias");
  assert.ok(smokeRequests.some(([method]) => method === "tools/list"), "control: discovery");
  assert.ok(smokeRequests.some(([method, params]) =>
    method === "tools/call" && params.name === "list_fixtures"), "control: listing");

  for (const [method, params] of smokeRequests) {
    const remote = await rpc(handle, method, params, { "MCP-Protocol-Version": "2025-11-25" });
    const local = await stdio.handle({ jsonrpc: "2.0", id: 1, method, params });
    if (method === "tools/list") {
      local.result.tools = local.result.tools.filter((tool) => names.includes(tool.name));
    }
    if (params.name === "describe_fixture") {
      const path = params.arguments.path;
      assert.equal(remote.result?.structuredContent?.path, path, `smoke must describe ${path}`);
    }
    assert.deepEqual(remote, local, JSON.stringify({ method, params }));
  }
}

test("deploy smoke requests match stdio on the bundled Worker and built index", async (t) => {
  const requests = intercept(t);
  await checkSmokeParity(bundledWorker.fetch);
  const format = smokeAlias.split("/")[0];
  const reply = await call(bundledWorker.fetch, "list_fixtures", { format, limit: 250 });
  const page = reply.result.structuredContent;
  assert.equal(page.next_offset, null);
  const paths = page.fixtures.map((entry) => entry.path);
  assert.ok(
    manifest.fixtures.some((entry) => entry.format === format &&
      !aliases.has(entry.path) && paths.includes(entry.path)),
    "control: the format listing has originals",
  );
  assert.ok(!paths.includes(smokeAlias), "the alias is excluded from the complete format listing");
  assert.deepEqual(requests.map(({ target }) => target), [compactIndex]);
});

test("the smoke parity guard fails when the built index lacks its alias path", async (t) => {
  intercept(t, (body) => {
    const document = JSON.parse(body);
    const row = document.fixtures.path.indexOf(smokeAlias);
    assert.ok(row >= 0, "control: the built index has the alias");
    document.fixtures.path[row] = `absent/${smokeAlias}`;
    return Response.json(document);
  });
  await assert.rejects(checkSmokeParity(start()), /smoke must describe/);
});

test("both tools reuse a warm index, keep it on 304, and see its next version", async (t) => {
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
  const describe = () => call(handle, "describe_fixture", { path: "pdf/minimal.pdf" });
  assert.equal((await describe()).result.structuredContent.catalog_version, version);
  assert.deepEqual(await list({ format: "pdf" }), tagged);
  assert.deepEqual(requests.map(({ target }) => target), [compactIndex]);
  now += 60_001;
  assert.deepEqual(await list({ format: "pdf" }), tagged);
  assert.deepEqual(requests.at(-1).headers, { "If-None-Match": `"${version}"` });
  version = "1.99.0";
  now += 60_001;
  assert.equal((await describe()).result.structuredContent.catalog_version, version);
  assert.equal((await list({})).result.structuredContent.catalog_version, version);
  assert.equal(requests.length, 3);
  assert.deepEqual(requests.slice(-2), [
    { target: compactIndex, headers: { "If-None-Match": `"${manifest.catalog_version}"` } },
    { target: compactIndex, headers: { "If-None-Match": `"${manifest.catalog_version}"` } },
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
  assert.deepEqual(requests.map(({ target }) => target), [compactIndex]);
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
  assert.deepEqual(requests.map(({ target }) => target), [compactIndex]);
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
