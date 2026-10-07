// `loremfile mcp` against the loopback server (server.js): a client of each protocol era
// talks to the real command over stdio, and the tool list both see must be the README's.

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, test } from "node:test";
import { fileURLToPath } from "node:url";

import * as api from "../src/api.js";
import * as mcp from "../src/mcp.js";
import { BODIES, startServer } from "./server.js";

const BIN = fileURLToPath(new URL("../bin/loremfile.js", import.meta.url));
const README = fileURLToPath(new URL("../README.md", import.meta.url));
const META = {
  "io.modelcontextprotocol/protocolVersion": mcp.MODERN,
  "io.modelcontextprotocol/clientCapabilities": {},
  "io.modelcontextprotocol/clientInfo": { name: "loremfile-test", version: "0" },
};

let server;
let scratch;
let child;

beforeEach(async () => {
  server = await startServer();
  // Canonical, as the server resolves it: on macOS the temporary directory is a symlink.
  scratch = await realpath(await mkdtemp(join(tmpdir(), "loremfile-mcp-")));
});

afterEach(async () => {
  if (child) {
    await child.close();
    child = undefined;
  }
  await server.close();
  await rm(scratch, { recursive: true, force: true });
});

/** The real command as a subprocess, with a minimal JSON-RPC client on its stdio. */
function start() {
  const proc = spawn(process.execPath, [BIN, "mcp"], {
    env: { ...process.env, [api.OVERRIDE]: server.base },
    cwd: scratch,
    stdio: ["pipe", "pipe", "pipe"],
  });
  const lines = [];
  const waiting = new Map();
  let buffer = "";
  proc.stdout.setEncoding("utf8");
  proc.stdout.on("data", (chunk) => {
    buffer += chunk;
    let cut;
    while ((cut = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 1);
      lines.push(line);
      const message = JSON.parse(line); // anything else on stdout fails the test here
      waiting.get(message.id)?.(message);
      waiting.delete(message.id);
    }
  });
  let next = 1;
  const exited = new Promise((resolve) => proc.on("exit", (code) => resolve(code)));
  return {
    lines,
    send(message) {
      proc.stdin.write(`${JSON.stringify(message)}\n`);
    },
    request(method, params) {
      const id = next++;
      const reply = new Promise((resolve) => waiting.set(id, resolve));
      this.send({ jsonrpc: "2.0", id, method, ...(params === undefined ? {} : { params }) });
      return reply;
    },
    async close() {
      proc.stdin.end();
      return exited;
    },
  };
}

function modern(method, params = {}) {
  return child.request(method, { ...params, _meta: META });
}

async function legacy() {
  const reply = await child.request("initialize", {
    protocolVersion: mcp.LEGACY,
    capabilities: {},
    clientInfo: { name: "loremfile-test", version: "0" },
  });
  child.send({ jsonrpc: "2.0", method: "notifications/initialized" });
  return reply;
}

/** The README's tool table: name, every argument, and which are required. */
async function documented() {
  const text = await readFile(README, "utf8");
  const section = text.slice(text.indexOf("## MCP server"), text.indexOf("## What it will not do"));
  const rows = section.split("\n").filter((line) => line.startsWith("| `"));
  return Object.fromEntries(
    rows.map((row) => {
      const [, name, args] = row.split("|").map((cell) => cell.trim());
      const found = [...args.matchAll(/`([a-z_]+)`( \(required\))?/g)];
      return [
        name.replaceAll("`", ""),
        {
          args: found.map((m) => m[1]).sort(),
          required: found
            .filter((m) => m[2])
            .map((m) => m[1])
            .sort(),
        },
      ];
    }),
  );
}

function surface(tools) {
  return Object.fromEntries(
    tools.map((tool) => [
      tool.name,
      {
        args: Object.keys(tool.inputSchema.properties).sort(),
        required: [...(tool.inputSchema.required ?? [])].sort(),
      },
    ]),
  );
}

async function call(name, args, era = "modern") {
  const params = { name, arguments: args };
  const reply =
    era === "modern"
      ? await modern("tools/call", params)
      : await child.request("tools/call", params);
  assert.equal(reply.error, undefined, JSON.stringify(reply.error));
  return reply.result;
}

// --- the surface, as each era sees it --------------------------------------------------------

test("the README documents exactly the three tools", async () => {
  // The control for the comparisons below: they hold vacuously if the table parses to nothing.
  assert.deepEqual(Object.keys(await documented()), [
    "list_fixtures",
    "describe_fixture",
    "verify_file",
  ]);
});

test("a 2026-07-28 client discovers the server and lists the documented tools", async () => {
  child = start();
  const discovered = await modern("server/discover");
  assert.equal(discovered.result.resultType, "complete");
  assert.deepEqual(discovered.result.supportedVersions, [mcp.MODERN, mcp.LEGACY]);
  assert.deepEqual(discovered.result.capabilities, { tools: {} });
  assert.equal(discovered.result._meta["io.modelcontextprotocol/serverInfo"].name, "loremfile");

  const listed = (await modern("tools/list")).result;
  assert.equal(listed.resultType, "complete");
  assert.equal(listed.cacheScope, "public");
  assert.deepEqual(surface(listed.tools), await documented());
});

test("a 2025-11-25 client initializes and lists the same documented tools", async () => {
  child = start();
  const opened = await legacy();
  assert.equal(opened.result.protocolVersion, mcp.LEGACY);
  assert.deepEqual(opened.result.capabilities, { tools: {} });
  assert.equal(opened.result.serverInfo.name, "loremfile");

  const listed = (await child.request("tools/list")).result;
  assert.equal(listed.resultType, undefined, "a 2025-11-25 result has no resultType");
  assert.deepEqual(surface(listed.tools), await documented());
  assert.deepEqual((await child.request("ping")).result, {});
});

test("the paging bounds the schema advertises are the ones the server enforces", () => {
  const [list] = mcp.TOOLS;
  assert.equal(list.inputSchema.properties.limit.default, mcp.DEFAULT_LIMIT);
  assert.equal(list.inputSchema.properties.limit.maximum, mcp.MAX_LIMIT);
});

test("both eras get identical tool definitions, every one read-only", async () => {
  child = start();
  const now = (await modern("tools/list")).result.tools;
  await legacy();
  const then = (await child.request("tools/list")).result.tools;
  assert.deepEqual(now, then);
  for (const tool of now) {
    assert.equal(tool.annotations.readOnlyHint, true, tool.name);
    assert.equal(tool.annotations.destructiveHint, false, tool.name);
  }
});

// --- versions and malformed requests: each guard, watched firing -----------------------------

test("an unknown version is refused with the versions this server speaks", async () => {
  child = start();
  const reply = await child.request("tools/list", {
    _meta: { ...META, "io.modelcontextprotocol/protocolVersion": "1999-01-01" },
  });
  assert.equal(reply.error.code, mcp.CODES.UNSUPPORTED_VERSION);
  assert.deepEqual(reply.error.data, {
    supported: [mcp.MODERN, mcp.LEGACY],
    requested: "1999-01-01",
  });
});

test("an older initialize is answered with 2025-11-25, as the handshake requires", async () => {
  child = start();
  const reply = await child.request("initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
  });
  assert.equal(reply.result.protocolVersion, mcp.LEGACY);
});

test("a request with neither _meta nor a session is invalid", async () => {
  child = start();
  const reply = await child.request("tools/list");
  assert.equal(reply.error.code, mcp.CODES.INVALID_PARAMS);
  assert.match(reply.error.message, /protocolVersion/);
});

test("a modern request without client capabilities is invalid", async () => {
  child = start();
  const { "io.modelcontextprotocol/clientCapabilities": _, ...partial } = META;
  const reply = await child.request("tools/list", { _meta: partial });
  assert.equal(reply.error.code, mcp.CODES.INVALID_PARAMS);
});

test("unknown methods and tools are protocol errors; notifications get no reply", async () => {
  child = start();
  child.send({ jsonrpc: "2.0", method: "notifications/cancelled", params: { requestId: 9 } });
  assert.equal((await modern("resources/list")).error.code, mcp.CODES.METHOD_NOT_FOUND);
  assert.equal(
    (await modern("ping")).error.code,
    mcp.CODES.METHOD_NOT_FOUND,
    "no ping in 2026-07-28",
  );
  const unknown = await modern("tools/call", { name: "download_fixture", arguments: {} });
  assert.equal(unknown.error.code, mcp.CODES.INVALID_PARAMS);
  // Two requests went out after the notification and exactly two replies came back.
  assert.equal(child.lines.length, 3);
});

// --- the tools -------------------------------------------------------------------------------

test("list_fixtures pages through the published fixtures and says where it is", async () => {
  child = start();
  const all = (await call("list_fixtures", {})).structuredContent;
  assert.equal(all.total, 5, "the withdrawn fixture is not listed");
  assert.equal(all.limit, mcp.DEFAULT_LIMIT);
  assert.equal(all.next_offset, null);
  assert.deepEqual(
    all.fixtures.map((f) => f.path),
    ["bin/large.bin", "pdf/other.pdf", "pdf/small.pdf", "svg/square.svg", "txt/notes.txt"],
  );
  assert.equal(all.fixtures[2].url, `${server.base}pdf/small.pdf`);

  const first = (await call("list_fixtures", { limit: 2 })).structuredContent;
  assert.deepEqual([first.count, first.next_offset, first.total], [2, 2, 5]);
  const last = (await call("list_fixtures", { limit: 2, offset: 4 })).structuredContent;
  assert.deepEqual([last.count, last.next_offset], [1, null]);
});

test("list_fixtures filters as `loremfile list` does", async () => {
  child = start();
  const paths = async (args) =>
    (await call("list_fixtures", args)).structuredContent.fixtures.map((f) => f.path);
  assert.deepEqual(await paths({ format: ["pdf"] }), ["pdf/other.pdf", "pdf/small.pdf"]);
  assert.deepEqual(await paths({ format: "svg" }), ["svg/square.svg"]);
  assert.deepEqual(await paths({ tag: ["txt", "svg"] }), ["svg/square.svg", "txt/notes.txt"]);
  assert.deepEqual(await paths({ format: ["pdf"], max_bytes: 17 }), ["pdf/small.pdf"]);
});

test("list_fixtures refuses arguments outside its schema as tool errors", async () => {
  child = start();
  for (const args of [
    { limit: 0 },
    { limit: mcp.MAX_LIMIT + 1 },
    { offset: -1 },
    { sort: "size" },
    { format: [1] },
  ]) {
    const result = await call("list_fixtures", args);
    assert.equal(result.isError, true, JSON.stringify(args));
  }
});

test("every structured result is also its serialized JSON, for older clients", async () => {
  child = start();
  const result = await call("describe_fixture", { path: "pdf/small.pdf" }, "modern");
  assert.deepEqual(JSON.parse(result.content[0].text), result.structuredContent);
});

test("describe_fixture returns the manifest entry, and names a path it does not know", async () => {
  child = start();
  const entry = (await call("describe_fixture", { path: "pdf/small.pdf" })).structuredContent;
  assert.equal(entry.bytes, BODIES["pdf/small.pdf"].length);
  assert.equal(entry.url, `${server.base}pdf/small.pdf`);
  assert.equal(entry.catalog_version, "9.9.9");
  assert.match(entry.sha256, /^[0-9a-f]{64}$/);
  for (const path of ["pdf/nope.pdf", "pdf/withdrawn.pdf"]) {
    const missing = await call("describe_fixture", { path });
    assert.equal(missing.isError, true);
    assert.match(missing.content[0].text, new RegExp(path));
  }
});

test("verify_file reports ok, changed and missing, relative to its directory", async () => {
  child = start();
  const good = join(scratch, "small.pdf");
  await writeFile(good, BODIES["pdf/small.pdf"]);
  const bad = join(scratch, "bad.pdf");
  await writeFile(bad, Buffer.from("%PDF-1.4 something else\n"));
  const status = async (file) =>
    (await call("verify_file", { path: "pdf/small.pdf", file })).structuredContent;

  const ok = await status("small.pdf");
  assert.deepEqual([ok.status, ok.file, ok.actual_sha256], ["ok", good, ok.expected_sha256]);
  const changed = await status(bad);
  assert.equal(changed.status, "changed");
  assert.notEqual(changed.actual_sha256, changed.expected_sha256);
  assert.deepEqual(
    [(await status("absent.pdf")).status, (await status(scratch)).status],
    ["missing", "missing"],
  );
  assert.equal((await call("verify_file", { path: "pdf/nope.pdf", file: good })).isError, true);
});

test("no tool ever returns a file's bytes", async () => {
  child = start();
  await writeFile(join(scratch, "notes.txt"), BODIES["txt/notes.txt"]);
  await call("list_fixtures", {});
  for (const path of Object.keys(BODIES)) {
    await call("describe_fixture", { path });
  }
  await call("verify_file", { path: "txt/notes.txt", file: "notes.txt" });
  const out = child.lines.join("\n");
  for (const [path, body] of Object.entries(BODIES)) {
    if (path !== "bin/large.bin") {
      assert.ok(!out.includes(body.toString("utf8").trim()), path);
    }
  }
  // The control: the same check sees the bytes when they are there.
  assert.ok(`${out}\n${BODIES["txt/notes.txt"]}`.includes("lorem ipsum"));
});

test("the server exits cleanly when its input closes", async () => {
  child = start();
  await modern("server/discover");
  const code = await child.close();
  child = undefined;
  assert.equal(code, 0);
});

// --- in process ------------------------------------------------------------------------------

test("the manifest is read once per process, and again only after a failed read", async () => {
  let reads = 0;
  let fail = true;
  const server = mcp.createServer({
    load: async () => {
      reads += 1;
      if (fail) {
        fail = false;
        throw new api.Unreachable("connection reset");
      }
      return { catalog_version: "1.0.0", fixtures: [] };
    },
  });
  const ask = (id) =>
    server.handle({
      jsonrpc: "2.0",
      id,
      method: "tools/call",
      params: { name: "list_fixtures", arguments: {}, _meta: META },
    });
  const failed = await ask(1);
  assert.equal(failed.result.isError, true);
  assert.match(failed.result.content[0].text, /could not be read: connection reset/);
  await ask(2);
  await ask(3);
  assert.equal(reads, 2);
});

test("a line that is not JSON is a parse error, not a crash", async () => {
  const reply = await mcp.createServer().line("{not json");
  assert.equal(reply.error.code, mcp.CODES.PARSE);
});
