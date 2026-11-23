import { byPath } from "../client-js/src/mcp-fixtures.mjs";

export const BASE_URL = "https://loremfile.dev/";
const INDEX = "mcp-index.json";
const REVALIDATE_AFTER_MS = 60_000;

export class IndexError extends Error {}

function invalidColumns() {
  return new IndexError(`/${INDEX} has invalid fixture columns`);
}

function unpack(column, count) {
  const { values, rows } = column ?? {};
  if (!Array.isArray(values) || !Array.isArray(rows) || rows.length !== count) {
    throw invalidColumns();
  }
  return rows.map((row) => {
    if (!Number.isInteger(row) || row < 0 || row >= values.length) {
      throw invalidColumns();
    }
    return values[row];
  });
}

function unpackProps(packed, keys) {
  if (packed === null) {
    return null;
  }
  if (!Array.isArray(packed) || packed.length % 2 !== 0) {
    throw invalidColumns();
  }
  const pairs = [];
  for (let i = 0; i < packed.length; i += 2) {
    pairs.push([keys[packed[i]], packed[i + 1]]);
  }
  return Object.fromEntries(pairs);
}

function fixtureRows({ fixtures, aliases }) {
  const { path, bytes, description } = fixtures ?? {};
  if (!Array.isArray(path) ||
      ![bytes, description].every((column) => Array.isArray(column) && column.length === path.length) ||
      !Array.isArray(aliases) || !Array.isArray(fixtures.props?.keys)) {
    throw invalidColumns();
  }
  const aliasRows = new Set(aliases);
  const columns = Object.fromEntries(
    ["format", "mime", "sha256", "size_class", "tags", "added_in"].map((name) => [
      name, unpack(fixtures[name], path.length),
    ]),
  );
  const { keys } = fixtures.props;
  const props = unpack(fixtures.props, path.length);
  const entries = path.map((name, row) => ({
    path: name,
    format: columns.format[row],
    mime: columns.mime[row],
    bytes: bytes[row],
    sha256: columns.sha256[row],
    size_class: columns.size_class[row],
    tags: columns.tags[row],
    description: description[row],
    props: props[row],
    added_in: columns.added_in[row],
    isAlias: aliasRows.has(row),
  }));
  return {
    entries,
    describe(path) {
      const entry = byPath(entries, path);
      return { ...entry, props: unpackProps(entry.props, keys) };
    },
  };
}

async function readIndex(etag) {
  try {
    const response = await fetch(BASE_URL + INDEX, {
      headers: etag ? { "If-None-Match": etag } : {},
      redirect: "error",
    });
    if (etag && response.status === 304) {
      return null;
    }
    if (response.status !== 200) {
      throw new IndexError(`/${INDEX} answered HTTP ${response.status}`);
    }
    const data = await response.json();
    if (typeof data?.catalog_version !== "string" || !data.catalog_version) {
      throw new IndexError(`/${INDEX} has no catalog_version`);
    }
    return {
      version: data.catalog_version,
      ...fixtureRows(data),
      etag: response.headers.get("etag"),
    };
  } catch (error) {
    if (error instanceof IndexError) {
      throw error;
    }
    throw new IndexError(`/${INDEX} could not be read as JSON`);
  }
}

export function createCatalog() {
  let cached;

  return async function loadCatalog() {
    if (cached && Date.now() < cached.checkAfter) {
      return cached;
    }
    // Cache resolved data only. Cloudflare fetch I/O belongs to the initiating request.
    const previous = cached;
    const result = await readIndex(previous?.etag);
    if (cached === previous) {
      cached = { ...(result ?? previous), checkAfter: Date.now() + REVALIDATE_AFTER_MS };
    }
    return cached;
  };
}
