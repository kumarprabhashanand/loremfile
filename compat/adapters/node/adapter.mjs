// The Node adapter: one reader, one file, one JSON object on stdout (compat/README.md).
//
//   node adapter.mjs <reader-id> <path> [--password P] [--delimiter D]
//
// Node's standard library only, and no imports of this repository. Each reader opens the file the
// way its own documentation shows, reads all of it, and reports only what the reader gives
// natively, under the manifest's names. Node has no standard-library reader for zip, tar, CSV, XML,
// images or WAV, so those formats have no reader here (compat/readers.yaml).
import { readFileSync } from "node:fs";
import { X509Certificate } from "node:crypto";
import { gunzipSync } from "node:zlib";

const ERROR_LIMIT = 200;

function gzipReader(path) {
  return { uncompressed_bytes: gunzipSync(readFileSync(path)).length };
}

function jsonReader(path) {
  const value = JSON.parse(readFileSync(path, "utf8"));
  const report = {};
  if (Array.isArray(value)) {
    report.top_type = "array";
    report.items = value.length;
  } else if (value === null) {
    report.top_type = "null";
  } else if (typeof value === "object") {
    report.top_type = "object";
    report.items = Object.keys(value).length;
  } else {
    report.top_type = typeof value === "number" || typeof value === "bigint" ? "number" : typeof value;
  }
  return report;
}

// A named exception (readers.yaml): X509Certificate gives the subject, the issuer and the
// subject alternative names as text and the serial as hexadecimal text; the adapter takes the CN
// from the name, the DNS entries from the names, and the serial as the integer it spells.
function certificateReader(path) {
  const cert = new X509Certificate(readFileSync(path));
  const common = (name) => /^CN=(.*)$/m.exec(name ?? "")?.[1];
  const names = (cert.subjectAltName ?? "")
    .split(", ")
    .filter((entry) => entry.startsWith("DNS:"))
    .map((entry) => entry.slice(4));
  const report = {
    serial: BigInt(`0x${cert.serialNumber}`),
    dns_names: names,
  };
  const subject = common(cert.subject);
  const issuer = common(cert.issuer);
  if (subject !== undefined) report.subject_cn = subject;
  if (issuer !== undefined) report.issuer_cn = issuer;
  return report;
}

const READERS = {
  "node/JSON": jsonReader,
  "node/crypto.X509Certificate": certificateReader,
  "node/zlib": gzipReader,
};

/** JSON text with keys sorted and a BigInt written as the number it is, which JSON.stringify refuses. */
function emit(value) {
  if (typeof value === "bigint") return value.toString();
  if (Array.isArray(value)) return `[${value.map(emit).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${emit(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function firstLine(text) {
  return String(text ?? "").trim().split("\n")[0].slice(0, ERROR_LIMIT);
}

function main(argv) {
  const [readerId, path] = argv;
  if (readerId === undefined || path === undefined) {
    process.stderr.write("usage: adapter.mjs <reader-id> <path> [--password P] [--delimiter D]\n");
    return 2;
  }
  const reader = READERS[readerId];
  if (reader === undefined) {
    process.stderr.write(`unknown reader: ${readerId}\n`);
    return 2;
  }
  let result;
  try {
    result = { outcome: "reads", props: reader(path) };
  } catch (error) {
    const message = firstLine(error?.message) || (error?.name ?? "Error");
    result = {
      outcome: "refuses",
      error_type: error?.constructor?.name ?? "Error",
      error: error?.code ? firstLine(`${error.code}: ${message}`) : message,
    };
  }
  process.stdout.write(`${emit(result)}\n`);
  return 0;
}

process.exitCode = main(process.argv.slice(2));
