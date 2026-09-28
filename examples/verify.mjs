// Fetch one fixture and check it against the hash in the manifest. Node 18+, no packages.
import { createHash } from "node:crypto";

const BASE = "https://loremfile.dev/";
const WANTED = "pdf/minimal.pdf";

const manifest = await (await fetch(BASE + "manifest.json")).json();
const entry = manifest.fixtures.find((f) => f.path === WANTED);

const body = Buffer.from(await (await fetch(BASE + WANTED)).arrayBuffer());
const digest = createHash("sha256").update(body).digest("hex");

if (digest !== entry.sha256) {
  throw new Error(`${WANTED}: got ${digest}, the manifest says ${entry.sha256}`);
}
console.log(`${WANTED}: ${body.length} bytes, sha256 matches`);
