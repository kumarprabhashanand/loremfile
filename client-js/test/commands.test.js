// get, list and verify against the loopback server (server.js), in process and as the real
// command — the sibling of client/tests/test_commands.py.

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, test } from "node:test";
import { fileURLToPath } from "node:url";

import * as api from "../src/api.js";
import { FAILED, OK, REFUSED, UNREACHABLE } from "../src/cli.js";
import { BODIES, HALF, run, startServer, waitFor } from "./server.js";

const BIN = fileURLToPath(new URL("../bin/loremfile.js", import.meta.url));
const PART = /^\.large\.bin\.[0-9a-f]+\.part$/;

let server;
let scratch;
let dest;
let paces;
let backoffs;
const waits = { ...api.timing };

beforeEach(async () => {
  server = await startServer();
  process.env[api.OVERRIDE] = server.base;
  scratch = await mkdtemp(join(tmpdir(), "loremfile-js-"));
  dest = join(scratch, "fixtures");
  // Downloads pause between files out of politeness to the real host; nothing here is the
  // real host, and a test suite that sleeps is a test suite nobody runs. The calls are kept.
  paces = [];
  backoffs = [];
  api.timing.pace = async () => {
    paces.push(1);
  };
  api.timing.backoff = async (ms) => {
    backoffs.push(ms);
  };
});

afterEach(async () => {
  Object.assign(api.timing, waits);
  delete process.env[api.OVERRIDE];
  await server.close();
  await rm(scratch, { recursive: true, force: true });
});

async function exists(file) {
  return stat(file).then(
    () => true,
    () => false,
  );
}

const fetched = () => server.state.requests.map((r) => r.path).filter((p) => p !== "manifest.json");

test("get writes the files it verified", async () => {
  assert.equal((await run(["get", "pdf/small.pdf", "txt/notes.txt", "--dest", dest])).code, OK);
  assert.deepEqual(await readFile(join(dest, "pdf", "small.pdf")), BODIES["pdf/small.pdf"]);
  assert.deepEqual(await readFile(join(dest, "txt", "notes.txt")), BODIES["txt/notes.txt"]);
});

test("get by format takes every file of it", async () => {
  assert.equal((await run(["get", "--format", "pdf", "--dest", dest])).code, OK);
  assert.deepEqual((await readdir(join(dest, "pdf"))).sort(), ["other.pdf", "small.pdf"]);
});

test("a withdrawn entry is not offered", async () => {
  assert.equal((await run(["get", "pdf/withdrawn.pdf", "--dest", dest])).code, REFUSED);
});

test("bytes that do not match are not written", async () => {
  // The reason the package exists: a file that fails its hash must not reach the disk, and
  // the command must not report success. Same length, one byte different.
  server.state.corrupt.add("pdf/small.pdf");
  const { code, err } = await run(["get", "pdf/small.pdf", "--dest", dest]);
  assert.equal(code, FAILED);
  assert.match(err, /downloaded sha256 [0-9a-f]{64}, the manifest says [0-9a-f]{64}/);
  assert.equal(await exists(join(dest, "pdf", "small.pdf")), false);
});

test("an unknown path is refused before anything is fetched", async () => {
  assert.equal((await run(["get", "pdf/not-real.pdf", "--dest", dest])).code, REFUSED);
  assert.equal(await exists(dest), false);
  assert.deepEqual(fetched(), []);
});

test("naming nothing is refused", async () => {
  assert.equal((await run(["get", "--dest", dest])).code, REFUSED);
});

test("a catalog version that has moved on is refused", async () => {
  const pinned = (version) =>
    run(["get", "pdf/small.pdf", "--dest", dest, "--catalog-version", version]);
  assert.equal((await pinned("1.0.0")).code, REFUSED);
  assert.equal((await pinned("9.9.9")).code, OK);
});

test("an existing file is kept unless --force", async () => {
  const file = join(dest, "pdf", "small.pdf");
  assert.equal((await run(["get", "pdf/small.pdf", "--dest", dest])).code, OK);
  await writeFile(file, "mine");
  assert.equal((await run(["get", "pdf/small.pdf", "--dest", dest])).code, OK);
  assert.equal(await readFile(file, "utf8"), "mine", "it overwrote without --force");
  assert.equal((await run(["get", "pdf/small.pdf", "--dest", dest, "--force"])).code, OK);
  assert.deepEqual(await readFile(file), BODIES["pdf/small.pdf"]);
});

test("a dry run fetches nothing", async () => {
  const argv = ["get", "--format", "pdf", "--dest", dest, "--dry-run", "--json"];
  const { code, out } = await run(argv);
  assert.equal(code, OK);
  const report = JSON.parse(out);
  assert.equal(report.summary.files, 2);
  assert.equal(
    report.summary.bytes,
    BODIES["pdf/small.pdf"].length + BODIES["pdf/other.pdf"].length,
  );
  assert.equal(await exists(dest), false);
  assert.deepEqual(fetched(), []);
});

test("list filters without downloading", async () => {
  const listed = async (...argv) =>
    new Set(JSON.parse((await run(["list", ...argv, "--json"])).out).items.map((i) => i.path));
  assert.deepEqual(await listed("--format", "pdf"), new Set(["pdf/small.pdf", "pdf/other.pdf"]));
  assert.deepEqual(await listed("--max-bytes", "13"), new Set(["txt/notes.txt"]));
  assert.deepEqual(await listed("--tag", "svg"), new Set(["svg/square.svg"]));
  assert.deepEqual(fetched(), []);
});

test("verify reports missing and changed files", async () => {
  assert.equal((await run(["get", "--format", "pdf", "--dest", dest])).code, OK);
  assert.equal((await run(["verify", "--dest", dest])).code, OK);

  await writeFile(join(dest, "pdf", "small.pdf"), "not what was published");
  const changed = await run(["verify", "--dest", dest]);
  assert.equal(changed.code, FAILED);
  assert.match(changed.out, /changed +pdf\/small\.pdf/);

  await rm(join(dest, "pdf", "small.pdf"));
  const missing = await run(["verify", "pdf/small.pdf", "--dest", dest]);
  assert.equal(missing.code, FAILED);
  assert.match(missing.out, /missing +pdf\/small\.pdf/);
});

test("verify on an empty directory checks nothing and says so", async () => {
  // A verify that finds no files must not report success over an empty set silently.
  await mkdir(dest);
  const { code, out } = await run(["verify", "--dest", dest, "--json"]);
  assert.equal(code, OK);
  assert.deepEqual(JSON.parse(out).summary, { checked: 0, failing: 0 });
});

test("a host that is not answering is a separate exit code", async () => {
  // Told apart from a verification failure on purpose: one is a broken network, the other a
  // broken file, and a script should be able to retry only the first.
  process.env[api.OVERRIDE] = "http://127.0.0.1:1/";
  assert.equal((await run(["get", "pdf/small.pdf", "--dest", dest])).code, UNREACHABLE);
});

test("a fixture path that would escape the destination is refused", () => {
  for (const bad of ["../elsewhere.txt", "/etc/passwd", "pdf/../../elsewhere", "pdf\\..\\..\\x"]) {
    assert.throws(() => api.target(dest, bad), api.Refused, bad);
  }
  assert.ok(api.target(dest, "pdf/small.pdf").endsWith(join("fixtures", "pdf", "small.pdf")));
});

test("a bad command line is a refusal, and help and version are not", async () => {
  for (const argv of [[], ["fetch"], ["list", "--nope"], ["list", "--max-bytes", "lots"]]) {
    assert.equal((await run(argv)).code, REFUSED, argv.join(" "));
  }
  assert.equal((await run(["--help"])).code, OK);
  assert.equal((await run(["get", "--help"])).code, OK);
  const version = await run(["--version"]);
  assert.equal(version.code, OK);
  assert.match(version.out, /^loremfile \d+\.\d+\.\d+\n$/);
});

// --- manners: one file at a time, a pause between them, patience with a 429 ---------------

test("files are fetched one at a time with a pause between them", async () => {
  // The first download is held halfway; a client that fetched in parallel would ask for the
  // second meanwhile. Small bodies alone cannot show it: they finish before a second request.
  const hold = server.hold("bin/large.bin");
  const running = run(["get", "bin/large.bin", "--format", "pdf", "--dest", dest]);
  await hold.reached;
  await new Promise((resolve) => setTimeout(resolve, 250));
  const duringTheFirst = fetched();
  hold.release();
  assert.equal((await running).code, OK);
  assert.deepEqual(duringTheFirst, ["bin/large.bin"], "a second file was asked for meanwhile");
  assert.deepEqual(fetched(), ["bin/large.bin", "pdf/other.pdf", "pdf/small.pdf"]);
  assert.equal(server.state.maxInFlight, 1, "two requests were open at once");
  assert.equal(paces.length, 2, "a pause between each pair of files, none after the last");
});

test("a 429 is waited out with growing pauses", async () => {
  server.state.tooMany.set("pdf/small.pdf", 2);
  assert.equal((await run(["get", "pdf/small.pdf", "--dest", dest])).code, OK);
  assert.deepEqual(backoffs, [2000, 4000]);
  assert.deepEqual(await readFile(join(dest, "pdf", "small.pdf")), BODIES["pdf/small.pdf"]);
});

test("a 429 that does not end is unreachable after the last pause", async () => {
  server.state.tooMany.set("pdf/small.pdf", 99);
  const { code, err } = await run(["get", "pdf/small.pdf", "--dest", dest]);
  assert.equal(code, UNREACHABLE);
  assert.match(err, /answered 429/);
  assert.deepEqual(backoffs, api.BACKOFF_MS);
  assert.equal(fetched().length, api.BACKOFF_MS.length + 1);
  assert.equal(await exists(join(dest, "pdf", "small.pdf")), false);
});

// --- redirects: followed on the same origin, refused off it -----------------------------

test("a redirect on the same origin is followed", async () => {
  server.state.redirect.set("txt/notes.txt", "/moved/txt/notes.txt");
  assert.equal((await run(["get", "txt/notes.txt", "--dest", dest])).code, OK);
  assert.deepEqual(fetched(), ["txt/notes.txt", "moved/txt/notes.txt"]);
  assert.deepEqual(await readFile(join(dest, "txt", "notes.txt")), BODIES["txt/notes.txt"]);
});

test("a redirect off the origin is refused and nothing is written", async () => {
  server.state.redirect.set("txt/notes.txt", "http://elsewhere.invalid/txt/notes.txt");
  const { code, err } = await run(["get", "txt/notes.txt", "--dest", dest]);
  assert.equal(code, REFUSED);
  assert.match(err, /redirected off loremfile\.dev/);
  assert.deepEqual(await readdir(join(dest, "txt")), []);
});

// --- how the bytes arrive (a 100 MB fixture must not be a 100 MB process) ----------------

async function partialHolding(atLeast) {
  return waitFor(async () => {
    const names = await readdir(join(dest, "bin")).catch(() => []);
    const name = names.find((n) => PART.test(n));
    if (!name) {
      return null;
    }
    const { size } = await stat(join(dest, "bin", name));
    return size >= atLeast ? { name, size, beside: names } : null;
  });
}

test("the body is streamed to a partial file beside its destination", async () => {
  // Half the body is on disk, under a hidden name in the destination directory, while the
  // other half has not been sent yet: so nothing waited for the whole body in memory, and the
  // final move is a rename on one filesystem rather than a copy from somewhere else.
  const hold = server.hold("bin/large.bin");
  const running = run(["get", "bin/large.bin", "--dest", dest]);
  await hold.reached;
  const seen = await partialHolding(HALF);
  hold.release();
  assert.equal((await running).code, OK);
  assert.ok(seen, "the first half never reached the disk before the second was sent");
  assert.ok(!seen.beside.includes("large.bin"), "something was at the published path early");
  assert.deepEqual(await readdir(join(dest, "bin")), ["large.bin"]);
  assert.deepEqual(await readFile(join(dest, "bin", "large.bin")), BODIES["bin/large.bin"]);
});

test("a mismatch leaves nothing behind, not even the partial file", async () => {
  // Not only nothing at the published path: nothing at all. A half-verified file under
  // another name is still a file somebody's glob will pick up. The partial file is seen
  // first, so this cannot pass on a client that never made one.
  server.state.corrupt.add("bin/large.bin");
  const hold = server.hold("bin/large.bin");
  const running = run(["get", "bin/large.bin", "--dest", dest]);
  await hold.reached;
  const seen = await partialHolding(1);
  hold.release();
  assert.equal((await running).code, FAILED);
  assert.ok(seen, "no partial file was ever written, so its absence proves nothing");
  assert.deepEqual(await readdir(join(dest, "bin")), [], "a partial file survived the mismatch");
});

test("an interrupted download leaves nothing behind", async () => {
  // The same promise when the connection drops rather than when the hash differs.
  const hold = server.hold("bin/large.bin", { cut: true });
  const running = run(["get", "bin/large.bin", "--dest", dest]);
  await hold.reached;
  const seen = await partialHolding(1);
  hold.release();
  assert.equal((await running).code, UNREACHABLE);
  assert.ok(seen, "no partial file was ever written, so its absence proves nothing");
  assert.deepEqual(await readdir(join(dest, "bin")), []);
});

// --- the installed command: its exit status is main's answer ----------------------------

function command(argv, base = server.base) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [BIN, ...argv], {
      cwd: scratch,
      env: { ...process.env, [api.OVERRIDE]: base },
    });
    let out = "";
    child.stdout.on("data", (chunk) => {
      out += chunk;
    });
    child.stderr.resume();
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, out }));
  });
}

test("the command's exit status is each of the four answers", async () => {
  assert.deepEqual(await command(["get", "pdf/small.pdf"]), {
    code: OK,
    out: `  written  pdf/small.pdf  17 bytes\nfiles=1, dest=loremfile-fixtures\n`,
  });
  assert.deepEqual(
    await readFile(join(scratch, "loremfile-fixtures", "pdf", "small.pdf")),
    BODIES["pdf/small.pdf"],
  );
  server.state.corrupt.add("txt/notes.txt");
  assert.equal((await command(["get", "txt/notes.txt"])).code, FAILED);
  assert.equal((await command(["get", "pdf/not-real.pdf"])).code, REFUSED);
  assert.equal((await command(["list"], "http://127.0.0.1:1/")).code, UNREACHABLE);
});
