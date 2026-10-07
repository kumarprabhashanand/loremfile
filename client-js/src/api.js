// Fetching fixtures from loremfile.dev, and checking every byte that arrives.
//
// Node built-ins only, on purpose: a client whose job is to download a file and hash it
// should not ask anyone to resolve a dependency tree, and the smaller the supply chain the
// less there is to audit. The sibling of client/src/loremfile_client/api.py, decision for
// decision.
//
// The one thing to know about this module: BASE_URL is a constant. There is no flag, no
// configuration file and no environment variable that points the client at another host —
// only a loopback override this project's own tests inject, refused for anything that is
// not 127.0.0.1, ::1 or localhost.

import { createHash, randomBytes } from "node:crypto";
import { createReadStream } from "node:fs";
import { mkdir, open, rename, rm, stat } from "node:fs/promises";
import http from "node:http";
import https from "node:https";
import path from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

/** The only host this client talks to. */
export const BASE_URL = "https://loremfile.dev/";

/** Injected by this project's tests so they never touch production. Loopback only. */
export const OVERRIDE = "LOREMFILE_BASE_URL";
export const LOOPBACK = ["http://127.0.0.1:", "http://localhost:", "http://[::1]:"];
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

// The published rate limit is 30 requests a second per client; one file at a time with a
// pause between them is well under it, and a 429 is answered with patience.
export const PAUSE_MS = 500;
export const BACKOFF_MS = [2000, 4000, 8000];
export const TIMEOUT_MS = 300_000;
export const USER_AGENT = "loremfile-client";

const REDIRECTS = new Set([301, 302, 303, 307, 308]);
const MAX_REDIRECTS = 10;

/** The request was wrong: an unknown path, a bad override, a version that has moved. */
export class Refused extends Error {}

/** loremfile.dev could not be read. */
export class Unreachable extends Error {}

/** Bytes arrived that are not the bytes the manifest describes. */
export class Mismatch extends Error {}

/**
 * The two waits, in one object so a test can make them instant and the rate manners stay a
 * property of this module rather than of whoever loops.
 */
export const timing = {
  pace: () => sleep(PAUSE_MS),
  backoff: (ms) => sleep(ms),
};

export function baseUrl(env = process.env) {
  const override = (env[OVERRIDE] ?? "").trim();
  if (!override) {
    return BASE_URL;
  }
  if (!isLoopback(override)) {
    throw new Refused(
      `${OVERRIDE} accepts a loopback address only, so that this project's tests can run ` +
        `without touching production; ${JSON.stringify(override)} is not one. There is no ` +
        "way to point this client at another host, by design.",
    );
  }
  return override.endsWith("/") ? override : `${override}/`;
}

function isLoopback(value) {
  // The prefix and the parsed host must agree: a prefix alone accepts a URL whose loopback
  // address is only the userinfo in front of an `@` and whose real host is somewhere else.
  if (!LOOPBACK.some((prefix) => value.startsWith(prefix))) {
    return false;
  }
  let url;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  return (
    url.protocol === "http:" && LOOPBACK_HOSTS.has(url.hostname) && !url.username && !url.password
  );
}

// Node reports a refused connection to a name with two addresses as an AggregateError whose
// message is empty; its code is the useful part.
function reason(error) {
  return error.message || error.code || String(error);
}

function request(url) {
  return new Promise((resolve, reject) => {
    const client = url.protocol === "https:" ? https : http;
    // identity, so the bytes hashed are the bytes published and never a CDN's compression.
    const headers = { "User-Agent": USER_AGENT, "Accept-Encoding": "identity" };
    const outgoing = client.get(url, { headers, timeout: TIMEOUT_MS }, resolve);
    outgoing.on("timeout", () => {
      outgoing.destroy(new Error(`no answer in ${TIMEOUT_MS / 1000} seconds`));
    });
    outgoing.on("error", reject);
  });
}

/**
 * An open response, retrying only a 429 — our own rate limit asking for patience.
 *
 * The retry is here, around opening, because that is where a 429 arrives. A stream that
 * fails halfway is not retried: this client's answer to a half-file is to delete it.
 * Redirects are followed only while they stay on the same origin.
 */
async function respond(relative) {
  const first = baseUrl() + relative.replace(/^\/+/, "");
  for (const pause of [...BACKOFF_MS, null]) {
    let url = new URL(first);
    let response;
    for (let hops = 0; ; hops += 1) {
      try {
        response = await request(url);
      } catch (error) {
        throw new Unreachable(`${first} could not be read: ${reason(error)}`);
      }
      if (!REDIRECTS.has(response.statusCode) || !response.headers.location) {
        break;
      }
      response.resume();
      const next = new URL(response.headers.location, url);
      if (next.origin !== url.origin) {
        throw new Refused(`${first} redirected off loremfile.dev, which is never followed`);
      }
      if (hops === MAX_REDIRECTS) {
        throw new Unreachable(`${first} redirected more than ${MAX_REDIRECTS} times`);
      }
      url = next;
    }
    const status = response.statusCode;
    if (status === 429 && pause !== null) {
      response.resume();
      await timing.backoff(pause);
      continue;
    }
    if (status < 200 || status >= 300) {
      response.resume();
      throw new Unreachable(`${first} answered ${status}`);
    }
    return response;
  }
  throw new Unreachable(`${first} is still answering 429`);
}

/**
 * The body in chunks, for fixtures — which run to 100 MB. A stream that breaks is
 * `Unreachable`; whatever the caller does with each chunk fails as itself.
 */
async function* stream(relative) {
  const response = await respond(relative);
  const chunks = response[Symbol.asyncIterator]();
  try {
    for (;;) {
      let next;
      try {
        next = await chunks.next();
      } catch (error) {
        throw new Unreachable(`${relative}: the download stopped: ${reason(error)}`);
      }
      if (next.done) {
        return;
      }
      yield next.value;
    }
  } finally {
    response.destroy();
  }
}

/** The whole body at once. For the manifest, which is JSON and has to be parsed. */
async function fetchWhole(relative) {
  const parts = [];
  for await (const chunk of stream(relative)) {
    parts.push(chunk);
  }
  return Buffer.concat(parts);
}

export async function manifest({ catalogVersion } = {}) {
  let document;
  try {
    document = JSON.parse((await fetchWhole("manifest.json")).toString("utf8"));
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Unreachable(`the manifest is not JSON: ${error.message}`);
    }
    throw error;
  }
  if (document === null || typeof document !== "object" || Array.isArray(document)) {
    throw new Unreachable("the manifest is not a JSON object");
  }
  const published = String(document.catalog_version ?? "");
  if (catalogVersion && published !== catalogVersion) {
    throw new Refused(`loremfile.dev publishes catalog ${published}, not ${catalogVersion}`);
  }
  return document;
}

export function active(document) {
  return (document.fixtures ?? []).filter((entry) => (entry.status ?? "active") === "active");
}

/** The entries a request names, or `Refused` naming what does not exist. */
export function select(entries, { paths = [], formats = [] } = {}) {
  const wantedPaths = new Set(paths);
  const wantedFormats = new Set(formats);
  if (wantedPaths.size === 0 && wantedFormats.size === 0) {
    throw new Refused("name at least one path or format");
  }
  const byPath = new Map(entries.map((entry) => [entry.path, entry]));
  const unknown = [...wantedPaths].filter((p) => !byPath.has(p)).sort();
  if (unknown.length > 0) {
    throw new Refused(`not published: ${unknown.join(", ")}`);
  }
  const publishedFormats = new Set(entries.map((entry) => entry.format));
  const unknownFormats = [...wantedFormats].filter((f) => !publishedFormats.has(f)).sort();
  if (unknownFormats.length > 0) {
    throw new Refused(`no such format: ${unknownFormats.join(", ")}`);
  }
  return entries
    .filter((entry) => wantedPaths.has(entry.path) || wantedFormats.has(entry.format))
    .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
}

/**
 * Where a fixture lands, refusing anything that would escape `dest`.
 *
 * The paths come from our own manifest, so this is not the day's most likely failure — but a
 * client that writes where a downloaded document tells it to is the shape of problem this
 * project publishes a fixture about (`edge/zip-directory-traversal-name.zip`). Backslashes
 * count as separators, because on Windows they are.
 */
export function target(dest, fixturePath) {
  const parts = fixturePath.split(/[\\/]/).filter((part) => part !== "" && part !== ".");
  if (
    fixturePath.startsWith("/") ||
    path.win32.isAbsolute(fixturePath) ||
    parts.includes("..") ||
    parts.length === 0
  ) {
    throw new Refused(`refusing ${JSON.stringify(fixturePath)}: not the shape of a fixture path`);
  }
  const root = path.resolve(dest);
  const resolved = path.resolve(root, ...parts);
  if (!resolved.startsWith(root.endsWith(path.sep) ? root : root + path.sep)) {
    throw new Refused(
      `refusing ${JSON.stringify(fixturePath)}: it would be written outside ${dest}`,
    );
  }
  return resolved;
}

/** The wait between two downloads. */
export function pace() {
  return timing.pace();
}

const GROUPED = new Intl.NumberFormat("en-US");

export function grouped(count) {
  return GROUPED.format(count);
}

/** What happened to one fixture. */
export class Result {
  constructor(fixturePath, status, detail = "") {
    this.path = fixturePath;
    this.status = status; // written | skipped | ok | missing | changed
    this.detail = detail;
  }

  get ok() {
    return ["written", "skipped", "ok"].includes(this.status);
  }
}

// Every byte of the chunk, or an error: a short write that went unnoticed would put a file
// whose hash was checked over bytes that never reached the disk at the published path.
async function writeAll(handle, chunk) {
  let offset = 0;
  while (offset < chunk.length) {
    const { bytesWritten } = await handle.write(chunk, offset, chunk.length - offset);
    if (bytesWritten === 0) {
      throw new Error("the disk accepted no more bytes");
    }
    offset += bytesWritten;
  }
  return offset;
}

async function exists(file) {
  try {
    await stat(file);
    return true;
  } catch {
    return false;
  }
}

/**
 * Fetch one fixture, hashing as it arrives, and put it at its path only if it matches.
 *
 * The bytes go to a temporary file in the destination directory, not to memory and not to
 * the system temporary directory: the first would cost 100 MB for the largest fixtures, and
 * the second could be another filesystem, where the final move is a copy rather than a
 * rename. A rename within one directory is atomic, so a reader of that directory sees either
 * no file or the whole verified one — and the temporary file is removed on a mismatch, on an
 * interrupted download, and on any other failure.
 */
export async function download(entry, dest, { force = false } = {}) {
  const destination = target(dest, entry.path);
  if (!force && (await exists(destination))) {
    return new Result(entry.path, "skipped", "already here; --force overwrites");
  }
  const directory = path.dirname(destination);
  await mkdir(directory, { recursive: true });

  const partial = path.join(
    directory,
    `.${path.basename(destination)}.${randomBytes(6).toString("hex")}.part`,
  );
  const digest = createHash("sha256");
  let written = 0;
  const handle = await open(partial, "wx");
  try {
    try {
      for await (const chunk of stream(entry.path)) {
        digest.update(chunk);
        written += await writeAll(handle, chunk);
      }
    } finally {
      await handle.close();
    }
    const actual = digest.digest("hex");
    if (actual !== entry.sha256) {
      throw new Mismatch(
        `${entry.path}: downloaded sha256 ${actual}, the manifest says ${entry.sha256}`,
      );
    }
    await rename(partial, destination);
  } finally {
    // A no-op once the rename has happened, and the whole point otherwise.
    await rm(partial, { force: true });
  }
  return new Result(entry.path, "written", `${grouped(written)} bytes`);
}

/** The SHA-256 of a file on disk, read a chunk at a time. */
export async function hashFile(file) {
  const digest = createHash("sha256");
  for await (const chunk of createReadStream(file)) {
    digest.update(chunk);
  }
  return digest.digest("hex");
}

/** A regular file's stat, or null for anything that is not one. */
export async function fileInfo(file) {
  try {
    const info = await stat(file);
    return info.isFile() ? info : null;
  } catch {
    return null;
  }
}

/** Whether a fixture is on disk at all, without reading it. */
export async function held(entry, dest) {
  return (await fileInfo(target(dest, entry.path))) !== null;
}

/** Check a fixture already on disk against the published manifest. */
export async function verify(entry, dest) {
  const destination = target(dest, entry.path);
  const info = await fileInfo(destination);
  if (info === null) {
    return new Result(entry.path, "missing", `not in ${dest}`);
  }
  const actual = await hashFile(destination);
  if (actual !== entry.sha256) {
    const expected = String(entry.sha256).slice(0, 12);
    return new Result(entry.path, "changed", `sha256 ${actual.slice(0, 12)}, expected ${expected}`);
  }
  return new Result(entry.path, "ok", `${grouped(info.size)} bytes`);
}
