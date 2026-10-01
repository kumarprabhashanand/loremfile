// The tarball carries the client and nothing else — the sibling of
// client/tests/test_packaging.py.
//
// Read off the built artifact, not the source tree: the point is what a user installs. CI runs
// `npm pack` before these, and the absence of a tarball fails rather than skips — a packaging
// guard that quietly does not run is the packaging guard that lets the deploy tooling out.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";

const CLIENT = fileURLToPath(new URL("..", import.meta.url));
const SOURCE = JSON.parse(readFileSync(join(CLIENT, "package.json"), "utf8"));

/** Exactly these, and a new one is a decision. npm adds package.json and README itself. */
const SHIPPED = [
  "package/README.md",
  "package/bin/loremfile.js",
  "package/package.json",
  "package/src/api.js",
  "package/src/cli.js",
];
/** Nothing whose path contains these may ever be in the tarball. Named, not counted. */
const NEVER = [
  "infra",
  "generators",
  "validators",
  "site",
  "upload",
  "release",
  "catalog",
  "manifest",
];
/** Every field through which npm would install something else or run something. */
const DEPENDENCY_FIELDS = [
  "dependencies",
  "devDependencies",
  "peerDependencies",
  "optionalDependencies",
  "bundleDependencies",
  "bundledDependencies",
];

function tarball() {
  const built = readdirSync(CLIENT).filter((name) => /^loremfile-.+\.tgz$/.test(name));
  assert.equal(built.length, 1, `want one tarball in ${CLIENT}, found ${built}; run: npm pack`);
  return join(CLIENT, built[0]);
}

/** Every entry in a .tgz, by name: a ustar reader, so the test needs no dependency either. */
function members(file) {
  const data = gunzipSync(readFileSync(file));
  const found = new Map();
  let longName = null;
  for (let offset = 0; offset + 512 <= data.length; ) {
    const header = data.subarray(offset, offset + 512);
    if (header.every((byte) => byte === 0)) {
      break;
    }
    const field = (start, length) =>
      header.subarray(start, start + length).toString("utf8").split("\0", 1)[0];
    const size = Number.parseInt(field(124, 12).trim() || "0", 8);
    const type = field(156, 1) || "0";
    const body = data.subarray(offset + 512, offset + 512 + size);
    const prefix = field(345, 155);
    const name = longName ?? (prefix ? `${prefix}/${field(0, 100)}` : field(0, 100));
    if (type === "x") {
      longName = /\d+ path=([^\n]*)\n/.exec(body.toString("utf8"))?.[1] ?? null;
    } else if (type !== "g") {
      found.set(name, { type, body });
      longName = null;
    }
    offset += 512 + Math.ceil(size / 512) * 512;
  }
  return found;
}

const packed = () => members(tarball());
const manifestOf = () => JSON.parse(packed().get("package/package.json").body.toString("utf8"));

test("the tarball holds the client and nothing else", () => {
  const names = [...packed().keys()].sort();
  assert.ok(names.length > 0, "empty-set control: the tarball was read and holds entries");
  assert.deepEqual(names, SHIPPED);
});

test("the tarball carries no repository tooling", () => {
  for (const name of packed().keys()) {
    const lowered = name.toLowerCase();
    assert.ok(!NEVER.some((part) => lowered.includes(`/${part}`)), name);
  }
});

test("every entry is a plain file", () => {
  for (const [name, { type }] of packed()) {
    assert.equal(type, "0", `${name} is tar type ${type}, not a file`);
  }
});

test("the tarball is the version package.json names", () => {
  assert.ok(tarball().endsWith(`loremfile-${SOURCE.version}.tgz`), tarball());
  assert.equal(manifestOf().version, SOURCE.version);
  assert.equal(manifestOf().name, "loremfile");
});

test("it installs nothing else and runs nothing on install", () => {
  const shipped = manifestOf();
  for (const field of DEPENDENCY_FIELDS) {
    assert.equal(shipped[field], undefined, `the tarball declares ${field}`);
  }
  // No scripts at all, so no preinstall, install, postinstall or prepare can ride along; and
  // no binding.gyp (the exact file list above), which npm would otherwise build on install.
  assert.equal(shipped.scripts, undefined, "the tarball declares scripts");
  assert.equal(shipped.gypfile, undefined);
});

test("the command is the client's bin, runnable by npx", () => {
  const shipped = manifestOf();
  assert.deepEqual(shipped.bin, { loremfile: "bin/loremfile.js" });
  assert.equal(shipped.type, "module");
  assert.deepEqual(shipped.engines, { node: ">=20" });
  const bin = packed().get("package/bin/loremfile.js").body.toString("utf8");
  assert.ok(bin.startsWith("#!/usr/bin/env node\n"), "the bin has no node shebang");
});

test("it names this repository, which trusted publishing compares against", () => {
  assert.deepEqual(manifestOf().repository, {
    type: "git",
    url: "git+https://github.com/kumarprabhashanand/loremfile.git",
    directory: "client-js",
  });
});
