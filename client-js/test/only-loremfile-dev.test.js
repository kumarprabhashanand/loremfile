// The client talks to loremfile.dev and to nothing else.
//
// Four ways of asking, because one of them alone would be easy to satisfy and still be wrong:
// the constant is the production host; the override refuses anything that is not loopback;
// no command-line option reaches the base URL; and no other host appears in the source at
// all. The override exists only so the rest of this suite can run without touching
// production — the same seam, and the same loopback-only rule, as the Python client.

import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import * as api from "../src/api.js";
import { COMMANDS, REFUSED } from "../src/cli.js";
import { run } from "./server.js";

const CLIENT = fileURLToPath(new URL("..", import.meta.url));

/** Every file the package ships code in — named, and checked to have been found. */
async function sources() {
  const found = [];
  for (const directory of ["bin", "src"]) {
    for (const name of await readdir(join(CLIENT, directory))) {
      if (name.endsWith(".js")) {
        const text = await readFile(join(CLIENT, directory, name), "utf8");
        found.push({ name: `${directory}/${name}`, text });
      }
    }
  }
  const names = found.map((s) => s.name).sort();
  assert.deepEqual(
    names,
    ["bin/loremfile.js", "src/api.js", "src/cli.js", "src/mcp.js"],
    "control: the scan",
  );
  return found;
}

test("the constant is production", () => {
  assert.equal(api.BASE_URL, "https://loremfile.dev/");
});

test("with no override it is production", () => {
  assert.equal(api.baseUrl({}), "https://loremfile.dev/");
  assert.equal(api.baseUrl({ [api.OVERRIDE]: "  " }), "https://loremfile.dev/");
});

const REFUSE = [
  "https://loremfile.dev.evil.test/", // the host name as a prefix
  "https://evil.test/loremfile.dev/", // and as a path
  "http://127.0.0.1.evil.test:8080/", // and the loopback address as a prefix
  "http://127.0.0.1:1@evil.test/", // a loopback prefix that is only the userinfo
  "http://localhost:80@evil.test/", // the same with the name
  "http://[::1]:1@evil.test/", // and with the IPv6 address
  "https://127.0.0.1:8080/", // loopback, but not the scheme the tests use
  "https://example.com/",
  "file:///etc/passwd",
  "http://169.254.169.254/", // the cloud metadata address
  " https://evil.test/", // leading space
];

for (const value of REFUSE) {
  test(`the override refuses ${JSON.stringify(value)}`, () => {
    assert.throws(
      () => api.baseUrl({ [api.OVERRIDE]: value }),
      (error) => error instanceof api.Refused && /loopback address only/.test(error.message),
    );
  });
}

for (const value of ["http://127.0.0.1:8080", "http://localhost:9/", "http://[::1]:1234"]) {
  test(`the override accepts ${value}`, () => {
    // The control: the refusals above are refusals, not a function that rejects everything.
    assert.ok(api.baseUrl({ [api.OVERRIDE]: value }).startsWith(value.replace(/\/$/, "")));
  });
}

test("a refused override is the command's refusal", async () => {
  process.env[api.OVERRIDE] = "http://127.0.0.1:1@evil.test/";
  try {
    const { code, err } = await run(["get", "pdf/minimal.pdf", "--dest", "never-written"]);
    assert.equal(code, REFUSED);
    assert.match(err, /loopback address only/);
  } finally {
    delete process.env[api.OVERRIDE];
  }
});

test("no command-line option reaches the host", () => {
  // A mirror option would contradict the README, so there must not be one — read off the
  // option table main parses with, so an option added later is caught.
  const options = new Set(Object.values(COMMANDS).flatMap((c) => Object.keys(c.options)));
  for (const named of ["dest", "format", "tag", "catalog-version", "max-bytes", "dry-run"]) {
    assert.ok(options.has(named), `control: the table holds --${named}`);
  }
  const pointing = /url|host|base|mirror|origin|server|registry/i;
  const reaching = [...options].filter((option) => pointing.test(option));
  assert.deepEqual(reaching, []);
});

test("no other host appears in the source", async () => {
  // The last way: whatever the code does with them, these are the only hosts in it.
  const urls = new Set();
  for (const { text } of await sources()) {
    for (const match of text.matchAll(/https?:\/\/[A-Za-z0-9.[\]:-]+/g)) {
      urls.add(match[0]);
    }
  }
  assert.deepEqual(
    urls,
    new Set(["https://loremfile.dev", "http://127.0.0.1:", "http://localhost:", "http://[::1]:"]),
  );
});

test("the client imports nothing but Node's built-ins", async () => {
  // Zero dependencies is a promise in the README and in package.json; this is what keeps it
  // true. Named modules, not a count: a new import is a decision.
  const allowed = new Set([
    "node:crypto",
    "node:fs",
    "node:fs/promises",
    "node:http",
    "node:https",
    "node:path",
    "node:readline",
    "node:timers/promises",
    "node:util",
    "./api.js",
    "./mcp.js",
    "../src/cli.js",
  ]);
  const imported = new Set();
  for (const { name, text } of await sources()) {
    const specifiers = /\bfrom\s*["']([^"']+)["']|^\s*import\s*["']([^"']+)["']/gm;
    for (const match of text.matchAll(specifiers)) {
      imported.add(match[1] ?? match[2]);
    }
    assert.doesNotMatch(text, /\brequire\s*\(|\bimport\s*\(/, `${name} loads code another way`);
  }
  for (const named of ["node:crypto", "node:http", "node:https", "./api.js", "../src/cli.js"]) {
    assert.ok(imported.has(named), `control: the scan found ${named}`);
  }
  assert.deepEqual([...imported].filter((m) => !allowed.has(m)), []);
});
