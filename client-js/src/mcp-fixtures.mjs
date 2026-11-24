// Argument validation and results for the two MCP tools that work over either transport.

export const DEFAULT_LIMIT = 50;
export const MAX_LIMIT = 250;

export const FIXTURE_INSTRUCTIONS =
  "loremfile.dev fixtures are dedicated to the public domain under CC0 1.0 Universal. " +
  "You may reuse them without attribution. Each published fixture has a stable URL " +
  "and the bytes at that URL never change.";

const FIXTURE_LICENSE = "CC0-1.0";
// The same extension pairs as site search. Keep the catalogue key in the result.
const FORMAT_SYNONYMS = new Map([
  ["jpg", "jpeg"], ["jpeg", "jpg"],
  ["tif", "tiff"], ["tiff", "tif"],
  ["htm", "html"], ["html", "htm"],
  ["yml", "yaml"], ["yaml", "yml"],
]);

/** A failure the caller can act on, returned with isError. */
export class ToolError extends Error {}

export function only(args, allowed) {
  if (args === null || typeof args !== "object" || Array.isArray(args)) {
    throw new ToolError("arguments must be an object");
  }
  const unknown = Object.keys(args).filter((key) => !allowed.includes(key));
  if (unknown.length > 0) {
    throw new ToolError(
      `unknown argument ${unknown.join(", ")}; this tool takes ${allowed.join(", ")}`,
    );
  }
  return args;
}

function strings(value, name) {
  if (value === undefined) {
    return [];
  }
  const list = typeof value === "string" ? [value] : value;
  if (!Array.isArray(list) || !list.every((item) => typeof item === "string")) {
    throw new ToolError(`${name} must be a list of strings`);
  }
  return list;
}

function integer(value, name, { min, max, fallback }) {
  if (value === undefined) {
    return fallback;
  }
  if (!Number.isInteger(value) || value < min || (max !== undefined && value > max)) {
    const range = max === undefined ? `at least ${min}` : `from ${min} to ${max}`;
    throw new ToolError(`${name} must be a whole number ${range}, not ${JSON.stringify(value)}`);
  }
  return value;
}

export function text(value, name) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new ToolError(`${name} is required and must be a non-empty string`);
  }
  return value;
}

export function listArguments(args) {
  only(args, ["format", "tag", "max_bytes", "limit", "offset"]);
  const requestedFormats = strings(args.format, "format");
  const formats = new Set(requestedFormats);
  for (const format of requestedFormats) {
    const synonym = FORMAT_SYNONYMS.get(format);
    if (synonym !== undefined) {
      formats.add(synonym);
    }
  }
  return {
    formats,
    tags: new Set(strings(args.tag, "tag")),
    maxBytes: integer(args.max_bytes, "max_bytes", { min: 0, fallback: null }),
    limit: integer(args.limit, "limit", { min: 1, max: MAX_LIMIT, fallback: DEFAULT_LIMIT }),
    offset: integer(args.offset, "offset", { min: 0, fallback: 0 }),
  };
}

export function describePath(args) {
  only(args, ["path"]);
  const { path } = args;
  if (path === undefined) {
    throw new ToolError("path is required");
  }
  if (typeof path !== "string") {
    throw new ToolError(`path must be a string, not ${JSON.stringify(path)}`);
  }
  if (path.trim() === "") {
    throw new ToolError(`path must be a non-empty string, not ${JSON.stringify(path)}`);
  }
  return path;
}

export function byPath(entries, fixturePath) {
  const entry = entries.find((candidate) => candidate.path === fixturePath);
  if (entry === undefined) {
    throw new ToolError(
      `no published fixture at ${JSON.stringify(fixturePath)}; ` +
        "list_fixtures shows what is published",
    );
  }
  return entry;
}

export function listResult(entries, query, version, baseUrl, isAlias) {
  const { formats, tags, maxBytes, limit, offset } = query;
  // Named lookups can return aliases. Listings skip them.
  const matches = entries
    .filter((e) => !isAlias(e))
    .filter((e) => formats.size === 0 || formats.has(e.format))
    .filter((e) => tags.size === 0 || (e.tags ?? []).some((tag) => tags.has(tag)))
    .filter((e) => maxBytes === null || e.bytes <= maxBytes)
    .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  const page = matches.slice(offset, offset + limit);
  return {
    catalog_version: String(version ?? ""),
    total: matches.length,
    offset,
    limit,
    count: page.length,
    next_offset: offset + limit < matches.length ? offset + limit : null,
    fixtures: page.map((e) => ({
      path: e.path,
      url: `${baseUrl}${e.path}`,
      format: e.format,
      mime: e.mime,
      bytes: e.bytes,
      sha256: e.sha256,
      license: FIXTURE_LICENSE,
      tags: e.tags ?? [],
      description: e.description ?? "",
    })),
  };
}

export function describeResult(entry, version, baseUrl) {
  const props = entry.props == null ? null : { ...entry.props };
  if (props !== null) {
    delete props.format;
  }
  return {
    catalog_version: String(version ?? ""),
    path: entry.path,
    url: `${baseUrl}${entry.path}`,
    format: entry.format,
    mime: entry.mime,
    bytes: entry.bytes,
    sha256: entry.sha256,
    license: FIXTURE_LICENSE,
    size_class: entry.size_class ?? null,
    tags: entry.tags ?? [],
    description: entry.description ?? "",
    props,
    added_in: entry.added_in ?? null,
  };
}
