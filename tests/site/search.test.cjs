// Run the browser script itself against a small DOM and a controllable fetch. No dependencies.
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const { test } = require("node:test");
const { runInNewContext } = require("node:vm");

const ROOT = resolve(__dirname, "../..");
const SCRIPT = readFileSync(resolve(ROOT, "site/static/site.js"), "utf8");
const MANIFEST = JSON.parse(readFileSync(resolve(ROOT, "manifest.json"), "utf8"));
const ROWS = MANIFEST.fixtures
  .filter((row) => (row.status ?? "active") === "active" && !row.supersededBy && row.generator !== "alias.copy")
  .sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0)
  .map((row) => ({
    path: row.path, bytes: row.bytes, size: `${row.bytes} bytes`,
    description: row.description, edge_case: row.edge_case,
  }));

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.listeners = {};
    this.attributes = {};
    this.hidden = false;
    this.value = "";
    this.text = "";
  }
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this.text = String(value); this.children = []; }
  appendChild(child) { this.children.push(child); return child; }
  insertBefore(child, before) {
    const at = this.children.indexOf(before);
    assert.notEqual(at, -1, "insertBefore names a child");
    this.children.splice(at, 0, child);
    return child;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  fire(name) {
    assert.equal(typeof this.listeners[name], "function", `${this.tagName} handles ${name}`);
    this.listeners[name]({ type: name });
  }
}

const settled = () => new Promise((done) => setImmediate(done));
const response = (rows) => ({ ok: true, json: async () => rows });

function browser({ rows = ROWS, fetch = async () => response(rows), script = SCRIPT } = {}) {
  const box = new Element("div");
  const input = new Element("input");
  input.dataset.index = "/search-index.json";
  const results = new Element("ul");
  box.hidden = true;
  box.appendChild(input);
  box.appendChild(results);
  const document = {
    getElementById: (id) => ({ q: input, results })[id] ?? null,
    querySelector: (selector) => selector === ".search-box" ? box : null,
    querySelectorAll: () => [],
    createElement: (tag) => new Element(tag),
    createTextNode: (text) => { const node = new Element("#text"); node.textContent = text; return node; },
  };
  runInNewContext(script, { document, navigator: {}, window: { fetch }, fetch });
  const nodes = (node) => [node, ...node.children.flatMap(nodes)];
  return {
    box, input, results,
    paths: () => nodes(results).filter((node) => node.tagName === "A").map((node) => node.href.slice(1)),
    button: (text) => nodes(box).find((node) => node.tagName === "BUTTON" && node.textContent === text),
    message: () => box.children.filter((node) => node.tagName === "P").map((node) => node.textContent).join(" "),
    async type(query) { input.value = query; input.fire("input"); await settled(); },
    async click(text) {
      const button = this.button(text);
      assert.ok(button && !button.hidden, `${text} is visible`);
      button.fire("click");
      await settled();
    },
  };
}

test("the search examples come from real published entries", () => {
  for (const path of ["aac/adts-30s.aac", "avro/people-1000.avro", "bin/10mb.bin", "pdf/minimal.pdf", "edge/zero-byte.pdf"]) {
    assert.ok(ROWS.some((row) => row.path === path), `control: the index contains ${path}`);
  }
});

test("wav matches WAV files, not the word wave", async () => {
  const app = browser();
  await app.type("wav");
  const paths = app.paths();
  assert.ok(paths.length >= 6, "control: enough real WAV files for the first six");
  assert.ok(paths.slice(0, 6).every((path) => path.startsWith("wav/")), paths.join(", "));
  assert.ok(!paths.includes("aac/adts-30s.aac"), "wave is not wav");
});

test("10 mb matches a whole size token, not 1000 or embedded", async () => {
  const app = browser();
  await app.type("10 mb");
  assert.ok(app.paths().includes("bin/10mb.bin"), "compact filename size tokens still match");
  assert.ok(!app.paths().includes("avro/people-1000.avro"));
});

test("pdf puts ordinary PDFs first and marks every edge/ result as an edge case", async () => {
  const app = browser();
  await app.type("pdf");
  while (app.button("Load more") && !app.button("Load more").hidden) { await app.click("Load more"); }
  assert.ok(app.paths()[0].startsWith("pdf/"), app.paths()[0]);
  const edge = app.results.children.filter((item) => item.children.some((node) => node.href?.startsWith("/edge/")));
  assert.ok(edge.some((item) => item.textContent.includes("edge/zero-byte.pdf")), "control: the deliberately empty PDF is present");
  for (const item of edge) { assert.match(item.textContent, /edge case/i); }
});

test("relevance tiers preserve index order within each tier", async () => {
  const rows = [
    { path: "txt/mention.txt", description: "A pdf example." },
    { path: "edge/broken.pdf", description: "Broken." },
    { path: "zip/pdf-archive.zip", description: "An archive." },
    { path: "pdf/z.pdf", description: "Ordinary." },
    { path: "pdf/a.pdf", description: "Ordinary." },
  ].map((row) => ({ ...row, size: "1 B" }));
  const app = browser({ rows });
  await app.type("pdf");
  assert.deepEqual(app.paths(), ["pdf/z.pdf", "pdf/a.pdf", "zip/pdf-archive.zip", "edge/broken.pdf", "txt/mention.txt"]);
});

test("new search handles the old index without the additive edge_case field", async () => {
  const rows = ROWS.map(({ edge_case, ...row }) => row);
  const app = browser({ rows });
  await app.type("pdf");
  while (app.button("Load more") && !app.button("Load more").hidden) { await app.click("Load more"); }
  assert.ok(app.paths()[0].startsWith("pdf/"));
  const edge = app.results.children.filter((item) => item.textContent.includes("edge/"));
  assert.ok(edge.length > 0, "control: legacy rows include edge cases");
  assert.ok(edge.every((item) => /edge case/i.test(item.textContent)));
});

test("the old script still consumes the new additive index", async () => {
  const script = readFileSync(resolve(__dirname, "fixtures/search-before-2026-11-16.js"), "utf8");
  const rows = ROWS.filter((row) => row.path === "pdf/minimal.pdf" || row.path === "edge/zero-byte.pdf");
  assert.equal(rows.length, 2, "control: the legacy consumer receives both new rows");
  const app = browser({ rows, script });
  await app.type("pdf");
  assert.deepEqual(app.paths(), rows.map((row) => row.path));
});

test("the catalogue edge_case flag also labels and demotes an edge case outside edge/", async () => {
  const rows = [
    { path: "pdf/broken.pdf", description: "A PDF.", size: "1 B", edge_case: true },
    { path: "pdf/usable.pdf", description: "A PDF.", size: "1 B", edge_case: false },
  ];
  const app = browser({ rows });
  await app.type("pdf");
  assert.deepEqual(app.paths(), ["pdf/usable.pdf", "pdf/broken.pdf"]);
  assert.match(app.results.children[1].textContent, /edge case/i);
});

test("the total and Load more expose every match beyond 20", async () => {
  const rows = Array.from({ length: 31 }, (_, i) => ({
    path: `pdf/file-${i}.pdf`, description: "A PDF.", size: `${i} B`,
  }));
  const app = browser({ rows });
  await app.type("pdf");
  assert.equal(app.paths().length, 20);
  assert.match(app.message(), /20 of 31/);
  await app.click("Load more");
  assert.deepEqual(app.paths(), rows.map((row) => row.path));
  assert.match(app.message(), /31 of 31/);
  assert.equal(app.button("Load more").hidden, true);
  await app.type("pdf");
  assert.equal(app.paths().length, 20, "a new query resets the page");
});

test("a rejected fetch shows an error and the next keystroke retries successfully", async () => {
  let calls = 0;
  const app = browser({ fetch: () => ++calls === 1 ? Promise.reject(new Error("offline")) : Promise.resolve(response(ROWS)) });
  await app.type("pdf");
  assert.match(app.message(), /could not load/i);
  assert.equal(app.paths().length, 0);
  assert.equal(app.button("Retry").hidden, false);
  await app.type("wav");
  assert.equal(calls, 2);
  assert.ok(app.paths()[0].startsWith("wav/"));
  assert.doesNotMatch(app.message(), /could not load/i);
});

test("the visible Retry button reloads after an HTTP error", async () => {
  let calls = 0;
  const app = browser({ fetch: async () => ++calls === 1 ? { ok: false, status: 503 } : response(ROWS) });
  await app.type("pdf");
  assert.match(app.message(), /could not load/i);
  await app.click("Retry");
  assert.equal(calls, 2);
  assert.ok(app.paths()[0].startsWith("pdf/"));
});

test("loading, no match and an empty query are distinct; in-flight results use the latest query", async () => {
  let finish;
  let calls = 0;
  const pending = new Promise((done) => { finish = done; });
  const app = browser({ fetch: () => { calls++; return pending; } });
  await app.type("pdf");
  assert.match(app.message(), /loading/i);
  await app.type("wav");
  assert.equal(calls, 1, "keystrokes share an in-flight request");
  finish(response(ROWS));
  await settled();
  assert.ok(app.paths()[0].startsWith("wav/"), "an earlier pdf query cannot overwrite wav");
  await app.type("nosuchfixturexyz");
  assert.match(app.message(), /no file matches/i);
  await app.type(" ");
  assert.equal(app.paths().length, 0);
  assert.equal(app.message(), "");
  assert.equal(app.button("Load more").hidden, true);
  assert.equal(app.button("Retry").hidden, true);
});
