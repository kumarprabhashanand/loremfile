// `loremfile get | list | verify`, the same three commands as the Python client.
//
// node:util's parseArgs rather than a framework, because the package has no dependencies and
// this is three subcommands. Exit codes are the contract: 0 fine, 1 a file failed
// verification or is missing, 2 the request was wrong, 3 loremfile.dev could not be read.

import { readFileSync } from "node:fs";
import { parseArgs } from "node:util";

import * as api from "./api.js";

export const OK = 0;
export const FAILED = 1;
export const REFUSED = 2;
export const UNREACHABLE = 3;
export const DEFAULT_DEST = "loremfile-fixtures";

export const VERSION = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf8"),
).version;

const SHARED = {
  json: { type: "boolean", help: "Print one JSON object." },
  quiet: { type: "boolean", help: "Print nothing but failures." },
  "catalog-version": {
    type: "string",
    value: "X.Y.Z",
    help: "Refuse to run unless loremfile.dev publishes this catalog version.",
  },
  help: { type: "boolean", short: "h", help: "Show this help." },
};
const FORMAT = { type: "string", multiple: true, value: "FMT" };
const DEST = { type: "string", value: "DIR", help: `Default: ${DEFAULT_DEST}` };

/** Every option each command accepts. Exported so a test can read them off, not the source. */
export const COMMANDS = {
  get: {
    summary: "Download fixtures and verify them.",
    positionals: "PATH… (e.g. pdf/minimal.pdf)",
    options: {
      format: { ...FORMAT, help: "Every published file of this format. Repeatable." },
      dest: DEST,
      force: { type: "boolean", help: "Overwrite files already there." },
      "dry-run": { type: "boolean", help: "List what would be fetched." },
      ...SHARED,
    },
  },
  list: {
    summary: "What is published, without downloading.",
    positionals: null,
    options: {
      format: { ...FORMAT, help: "Only this format. Repeatable." },
      tag: { type: "string", multiple: true, value: "TAG", help: "Only this tag. Repeatable." },
      "max-bytes": { type: "string", value: "N", help: "Only files of at most N bytes." },
      ...SHARED,
    },
  },
  verify: {
    summary: "Check files on disk against the manifest.",
    positionals: "PATH…",
    options: {
      format: { ...FORMAT, help: "Every published file of this format. Repeatable." },
      dest: DEST,
      ...SHARED,
    },
  },
};

class Usage extends Error {}

function usage() {
  return [
    `loremfile ${VERSION}`,
    "Download CC0 sample files from loremfile.dev and check every byte.",
    "",
    "usage: loremfile {get,list,verify} [options]",
    ...Object.entries(COMMANDS).map(([name, command]) => `  ${name.padEnd(8)}${command.summary}`),
    "",
    "`loremfile COMMAND --help` lists a command's options.",
    "Files come from loremfile.dev and nowhere else; there is no mirror option.",
    "",
  ].join("\n");
}

function commandHelp(name) {
  const command = COMMANDS[name];
  const positionals = command.positionals ? ` ${command.positionals}` : "";
  const lines = [`usage: loremfile ${name} [options]${positionals}`, command.summary, ""];
  for (const [option, spec] of Object.entries(command.options)) {
    const short = spec.short ? `-${spec.short}, ` : "";
    const flag = `${short}--${option}${spec.value ? ` ${spec.value}` : ""}`;
    lines.push(`  ${flag.padEnd(28)}${spec.help ?? ""}`);
  }
  return `${lines.join("\n")}\n`;
}

function parse(argv) {
  const [name, ...rest] = argv;
  if (name === undefined) {
    throw new Usage("name a command: get, list or verify");
  }
  if (!Object.hasOwn(COMMANDS, name)) {
    throw new Usage(`no such command: ${name}`);
  }
  const command = COMMANDS[name];
  // parseArgs rejects a `short` or `multiple` key that is present but undefined, so only the
  // keys a spec actually sets are passed on; `help` and `value` are for commandHelp alone.
  const options = Object.fromEntries(
    Object.entries(command.options).map(([option, { type, short, multiple }]) => [
      option,
      { type, ...(short ? { short } : {}), ...(multiple ? { multiple } : {}) },
    ]),
  );
  const allowPositionals = command.positionals !== null;
  let parsed;
  try {
    parsed = parseArgs({ args: rest, options, allowPositionals, strict: true });
  } catch (error) {
    if (String(error.code).startsWith("ERR_PARSE_ARGS")) {
      throw new Usage(error.message);
    }
    throw error;
  }
  const values = parsed.values;
  const args = {
    command: name,
    help: Boolean(values.help),
    paths: parsed.positionals,
    format: values.format ?? [],
    tag: values.tag ?? [],
    dest: values.dest ?? DEFAULT_DEST,
    force: Boolean(values.force),
    dryRun: Boolean(values["dry-run"]),
    json: Boolean(values.json),
    quiet: Boolean(values.quiet),
    catalogVersion: values["catalog-version"],
    maxBytes: null,
  };
  if (values["max-bytes"] !== undefined) {
    const text = values["max-bytes"].trim();
    if (!/^[+-]?\d+$/.test(text)) {
      throw new Usage(`--max-bytes takes a whole number, not ${JSON.stringify(text)}`);
    }
    args.maxBytes = Number(text);
  }
  return args;
}

function emit(args, summary, results, io) {
  if (args.json) {
    const items = results.map(({ path, status, detail }) => ({ path, status, detail }));
    io.out(`${JSON.stringify({ summary, items }, null, 2)}\n`);
    return;
  }
  for (const result of results) {
    if (!result.ok || !args.quiet) {
      const detail = result.detail ? `  ${result.detail}` : "";
      io.out(`  ${result.status.padEnd(8)} ${result.path}${detail}\n`);
    }
  }
  if (!args.quiet) {
    const pairs = Object.entries(summary).map(([key, value]) => `${key}=${value}`);
    io.out(`${pairs.join(", ")}\n`);
  }
}

async function runGet(args, io) {
  const published = api.active(await api.manifest({ catalogVersion: args.catalogVersion }));
  const entries = api.select(published, { paths: args.paths, formats: args.format });
  if (args.dryRun) {
    const total = entries.reduce((sum, entry) => sum + entry.bytes, 0);
    emit(
      args,
      { files: entries.length, bytes: total, dest: args.dest, "dry-run": true },
      entries.map((e) => new api.Result(e.path, "would fetch", `${api.grouped(e.bytes)} bytes`)),
      io,
    );
    return OK;
  }
  const results = [];
  for (const [index, entry] of entries.entries()) {
    results.push(await api.download(entry, args.dest, { force: args.force }));
    if (index + 1 < entries.length) {
      await api.pace();
    }
  }
  emit(args, { files: results.length, dest: args.dest }, results, io);
  return OK;
}

async function runList(args, io) {
  let entries = api.active(await api.manifest({ catalogVersion: args.catalogVersion }));
  if (args.format.length > 0) {
    entries = entries.filter((e) => args.format.includes(e.format));
  }
  if (args.tag.length > 0) {
    entries = entries.filter((e) => (e.tags ?? []).some((tag) => args.tag.includes(tag)));
  }
  if (args.maxBytes !== null) {
    entries = entries.filter((e) => e.bytes <= args.maxBytes);
  }
  const results = entries.map(
    (e) => new api.Result(e.path, "listed", `${api.grouped(e.bytes)} bytes  ${e.mime}`),
  );
  emit(args, { files: results.length }, results, io);
  return OK;
}

async function runVerify(args, io) {
  let entries = api.active(await api.manifest({ catalogVersion: args.catalogVersion }));
  if (args.paths.length > 0 || args.format.length > 0) {
    entries = api.select(entries, { paths: args.paths, formats: args.format });
  } else {
    // Everything the destination actually holds, so `verify` alone checks a directory.
    const held = [];
    for (const entry of entries) {
      if (await api.held(entry, args.dest)) {
        held.push(entry);
      }
    }
    entries = held;
  }
  const results = [];
  for (const entry of entries) {
    results.push(await api.verify(entry, args.dest));
  }
  const failing = results.filter((r) => !r.ok);
  emit(args, { checked: results.length, failing: failing.length }, results, io);
  return failing.length > 0 ? FAILED : OK;
}

const RUNNERS = { get: runGet, list: runList, verify: runVerify };

const STDIO = {
  out: (text) => process.stdout.write(text),
  err: (text) => process.stderr.write(text),
};

export async function main(argv, io = STDIO) {
  if (argv.length === 1 && (argv[0] === "--help" || argv[0] === "-h")) {
    io.out(usage());
    return OK;
  }
  if (argv.length === 1 && argv[0] === "--version") {
    io.out(`loremfile ${VERSION}\n`);
    return OK;
  }
  let args;
  try {
    args = parse(argv);
  } catch (error) {
    if (error instanceof Usage) {
      io.err(`loremfile: ${error.message}\n\n${usage()}`);
      return REFUSED;
    }
    throw error;
  }
  if (args.help) {
    io.out(commandHelp(args.command));
    return OK;
  }
  try {
    return await RUNNERS[args.command](args, io);
  } catch (error) {
    if (error instanceof api.Refused) {
      io.err(`loremfile: ${error.message}\n`);
      return REFUSED;
    }
    if (error instanceof api.Mismatch) {
      io.err(`loremfile: ${error.message}\n`);
      return FAILED;
    }
    if (error instanceof api.Unreachable) {
      io.err(`loremfile: ${error.message}\n`);
      return UNREACHABLE;
    }
    throw error;
  }
}
