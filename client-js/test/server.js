// A loremfile.dev that is not loremfile.dev.
//
// Every test runs against a loopback server that serves a handful of made-up fixtures. The
// client reaches it through LOREMFILE_BASE_URL, which it accepts only for a loopback address —
// so this server is also the reason that override exists, and only-loremfile-dev.test.js is
// what keeps it from becoming a way to point the client anywhere else.

import { createHash } from "node:crypto";
import http from "node:http";

import { main } from "../src/cli.js";

export function entry(path, body, { tags } = {}) {
  const format = path.split("/", 1)[0];
  return {
    path,
    format,
    bytes: body.length,
    sha256: createHash("sha256").update(body).digest("hex"),
    mime: "application/octet-stream",
    description: `a ${format} file`,
    tags: tags ?? [format],
    status: "active",
  };
}

/** Big enough to arrive in several chunks, so a test can stop it halfway. */
export const LARGE = Buffer.from(Array.from({ length: 256 * 1024 }, (_, i) => (i * 31) % 251));
export const HALF = LARGE.length / 2;

export const BODIES = {
  "pdf/small.pdf": Buffer.from("%PDF-1.4 pretend\n"),
  "pdf/other.pdf": Buffer.from("%PDF-1.4 also pretend\n"),
  "svg/square.svg": Buffer.from("<svg xmlns='http://www.w3.org/2000/svg'/>\n"),
  "txt/notes.txt": Buffer.from("lorem ipsum\n"),
  "bin/large.bin": LARGE,
};

export const MANIFEST = {
  catalog_version: "9.9.9",
  count: Object.keys(BODIES).length,
  fixtures: [
    ...Object.entries(BODIES).map(([path, body]) => entry(path, body)),
    { ...entry("pdf/withdrawn.pdf", Buffer.from("gone")), status: "removed" },
  ],
};

/** The same length, one byte different: a mismatch only a hash can see. */
function tampered(body) {
  const copy = Buffer.from(body);
  copy[copy.length - 1] ^= 0xff;
  return copy;
}

export async function startServer() {
  const state = {
    corrupt: new Set(),
    tooMany: new Map(), // path -> 429s still to send
    redirect: new Map(), // path -> Location
    holds: new Map(), // path -> { reached, release, cut }
    requests: [],
    inFlight: 0,
    maxInFlight: 0,
  };

  const server = http.createServer(async (request, response) => {
    state.inFlight += 1;
    state.maxInFlight = Math.max(state.maxInFlight, state.inFlight);
    // On "finish", when the last byte is handed over — before the client can have read it and
    // asked again — or on "close" for a response that never finishes. Once either way.
    let open = true;
    const done = () => {
      if (open) {
        open = false;
        state.inFlight -= 1;
      }
    };
    response.on("finish", done);
    response.on("close", done);
    const path = request.url.replace(/^\/+/, "");
    state.requests.push({ path, userAgent: request.headers["user-agent"] });

    const remaining = state.tooMany.get(path) ?? 0;
    if (remaining > 0) {
      state.tooMany.set(path, remaining - 1);
      response.writeHead(429).end();
      return;
    }
    if (state.redirect.has(path)) {
      response.writeHead(302, { Location: state.redirect.get(path) }).end();
      return;
    }
    let body;
    if (path === "manifest.json") {
      body = Buffer.from(JSON.stringify(MANIFEST));
    } else {
      const served = path.replace(/^moved\//, "");
      if (!Object.hasOwn(BODIES, served)) {
        response.writeHead(404).end();
        return;
      }
      body = state.corrupt.has(served) ? tampered(BODIES[served]) : BODIES[served];
    }
    response.writeHead(200, { "Content-Length": String(body.length) });
    const hold = state.holds.get(path);
    if (!hold) {
      response.end(body);
      return;
    }
    response.write(body.subarray(0, HALF));
    hold.arrive();
    await hold.released;
    if (hold.cut) {
      response.socket.destroy();
    } else {
      response.end(body.subarray(HALF));
    }
  });

  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return {
    base: `http://127.0.0.1:${server.address().port}/`,
    state,
    /** Stop `path` halfway: `reached` resolves once half is sent, and `release()` sends the
     * rest — or, with `cut`, drops the connection instead. */
    hold(path, { cut = false } = {}) {
      const hold = { cut };
      hold.reached = new Promise((resolve) => {
        hold.arrive = resolve;
      });
      hold.released = new Promise((resolve) => {
        hold.release = resolve;
      });
      state.holds.set(path, hold);
      return hold;
    },
    async close() {
      for (const hold of state.holds.values()) {
        hold.release();
      }
      server.closeAllConnections();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

/** main() with its output captured instead of printed. */
export async function run(argv) {
  let out = "";
  let err = "";
  const code = await main(argv, {
    out: (text) => {
      out += text;
    },
    err: (text) => {
      err += text;
    },
  });
  return { code, out, err };
}

/** Poll `probe` until it returns something, or give up and return null. */
export async function waitFor(probe, { timeoutMs = 5000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const found = await probe();
    if (found) {
      return found;
    }
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  return null;
}
