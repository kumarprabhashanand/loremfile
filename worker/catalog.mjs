export const BASE_URL = "https://loremfile.dev/";
const CROSS_FORMAT_INDEX = "mcp-index.json";
const REVALIDATE_AFTER_MS = 60_000;

export class IndexError extends Error {}

async function readIndex(path, etag) {
  try {
    const response = await fetch(BASE_URL + path, {
      headers: etag ? { "If-None-Match": etag } : {},
      redirect: "error",
    });
    if ((etag && response.status === 304) || response.status === 404) {
      return { status: response.status };
    }
    if (response.status !== 200) {
      throw new IndexError(`/${path} answered HTTP ${response.status}`);
    }
    const data = await response.json();
    if (typeof data?.catalog_version !== "string" || !data.catalog_version) {
      throw new IndexError(`/${path} has no catalog_version`);
    }
    return { status: 200, data, etag: response.headers.get("etag") };
  } catch (error) {
    if (error instanceof IndexError) {
      throw error;
    }
    throw new IndexError(`/${path} could not be read as JSON`);
  }
}

function listRows({ fixtures: columns }) {
  // Describe reads its full rows from the format index. Materialize only the columns for list.
  const fields = ["path", "format", "mime", "bytes", "tags", "description"];
  if (!fields.every((field) => Array.isArray(columns?.[field]) &&
      columns[field].length === columns.path.length)) {
    throw new IndexError(`/${CROSS_FORMAT_INDEX} has invalid fixture columns`);
  }
  return columns.path.map((path, index) => ({
    path,
    format: columns.format[index],
    mime: columns.mime[index],
    bytes: columns.bytes[index],
    tags: columns.tags[index],
    description: columns.description[index],
  }));
}

function formatRows({ fixtures, aliases }) {
  if (!Array.isArray(fixtures) || !Array.isArray(aliases)) {
    throw new IndexError("The format index has invalid fixture or alias rows");
  }
  return { fixtures, aliases };
}

export function createCatalog(knownFormats) {
  let version;
  let indexes = new Map();

  async function load(path, project) {
    const snapshot = indexes;
    const cached = snapshot.get(path);
    if (cached && Date.now() < cached.checkAfter) {
      return cached;
    }
    // Cache resolved data only. Cloudflare fetch I/O belongs to the initiating request.
    const { status, data, etag } = await readIndex(path, cached?.etag);
    if (status === 404) {
      return null;
    }
    if (status === 304) {
      cached.checkAfter = Date.now() + REVALIDATE_AFTER_MS;
      return cached;
    }
    const value = {
      version: data.catalog_version,
      rows: project(data),
      etag,
      checkAfter: Date.now() + REVALIDATE_AFTER_MS,
    };
    // An in-flight refresh must not discard a newer snapshot established by another request.
    if (snapshot === indexes) {
      if (version !== value.version) {
        version = value.version;
        indexes = new Map();
      }
      indexes.set(path, value);
    }
    return value;
  }

  async function perFormat(format) {
    return load(`${format}/index.json`, formatRows);
  }

  return {
    async list(formats) {
      const [format] = formats;
      if (formats.size === 1 && knownFormats.has(format)) {
        const index = await perFormat(format);
        if (index === null) {
          throw new IndexError(`/${format}/index.json answered HTTP 404`);
        }
        return { version: index.version, entries: index.rows.fixtures };
      }
      // Multiple explicit formats still take one read. The same index supplies the
      // catalog version for an empty result when the caller names an unknown format.
      const index = await load(CROSS_FORMAT_INDEX, listRows);
      if (index === null) {
        throw new IndexError(`/${CROSS_FORMAT_INDEX} answered HTTP 404`);
      }
      return { version: index.version, entries: index.rows };
    },
    async describe(path) {
      const [, format] = /^([a-z0-9]+)\//.exec(path) ?? [];
      const index = format ? await perFormat(format) : null;
      return index === null
        ? { entries: [] }
        : { version: index.version, entries: [...index.rows.fixtures, ...index.rows.aliases] };
    },
  };
}
