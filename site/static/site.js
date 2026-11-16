(function () {
  "use strict";

  var status = document.getElementById("copy-status");
  if (navigator.clipboard) {
    document.querySelectorAll("button.copy").forEach(function (button) {
      button.hidden = false;
      button.addEventListener("click", function () {
        navigator.clipboard.writeText(button.dataset.copy).then(
          function () { if (status) { status.textContent = "Copied " + button.dataset.copy; } },
          function () { if (status) { status.textContent = "Copy failed; select the link instead"; } }
        );
      });
    });
  }

  var box = document.querySelector(".search-box");
  var input = document.getElementById("q");
  var results = document.getElementById("results");
  if (!box || !input || !results || !window.fetch) { return; }
  box.hidden = false;

  var index = null;
  var loading = null;
  var failed = false;
  var visible = 20;
  var summary = document.createElement("p");
  summary.setAttribute("role", "status");
  summary.hidden = true;
  box.insertBefore(summary, results);
  var more = document.createElement("button");
  more.type = "button";
  more.textContent = "Load more";
  more.setAttribute("aria-controls", "results");
  more.hidden = true;
  box.appendChild(more);
  var retry = document.createElement("button");
  retry.type = "button";
  retry.textContent = "Retry";
  retry.hidden = true;
  box.appendChild(retry);

  function words(text) {
    var tokens = text.toLowerCase().match(/[a-z0-9]+(?:\.[0-9]+)?/g) || [];
    // A filename's 10mb is also the two whole tokens 10 and mb, never 100 or embedded.
    return tokens.reduce(function (all, token) {
      all.push(token);
      var size = /^(\d+(?:\.\d+)?)(b|kb|mb|gb|kib|mib|gib)$/.exec(token);
      if (size) { all.push(size[1], size[2]); }
      return all;
    }, []);
  }

  function edgeCase(row) {
    // Old indexes have no edge_case field. The edge/ prefix still identifies those rows.
    return row.edge_case === true || row.path.indexOf("edge/") === 0;
  }

  function matches(query) {
    var wanted = words(query);
    if (!wanted.length) { return []; }
    return index.map(function (row, position) {
      var path = row.path.toLowerCase();
      var pathWords = words(path);
      var descriptionWords = words(row.description);
      var inPath = wanted.every(function (word) { return pathWords.indexOf(word) !== -1; });
      var found = wanted.every(function (word) {
        return pathWords.indexOf(word) !== -1 || descriptionWords.indexOf(word) !== -1;
      });
      var format = path.split("/")[0];
      var extension = path.slice(path.lastIndexOf(".") + 1);
      var own = wanted.some(function (word) { return word === format || word === extension; });
      var tier = edgeCase(row) ? 2 : own ? 0 : inPath ? 1 : 3;
      return { row: row, position: position, tier: tier, found: found };
    }).filter(function (match) { return match.found; })
      .sort(function (a, b) { return a.tier - b.tier || a.position - b.position; });
  }

  function load() {
    if (index) { return Promise.resolve(); }
    if (!loading) {
      failed = false;
      loading = fetch(input.dataset.index)
        .then(function (response) {
          if (!response.ok) { throw new Error("The search index could not be read"); }
          return response.json();
        })
        .then(function (rows) {
          if (!Array.isArray(rows)) { throw new Error("The search index is not a list"); }
          index = rows;
        })
        .catch(function () {
          loading = null;
          failed = true;
        });
    }
    return loading;
  }

  function show() {
    var query = input.value.trim();
    results.textContent = "";
    summary.textContent = "";
    summary.hidden = !query;
    more.hidden = true;
    retry.hidden = true;
    if (!query) { return; }
    if (!index) {
      summary.textContent = failed ? "Could not load the search index." : "Loading files...";
      retry.hidden = !failed;
      return;
    }
    var found = matches(query);
    var shown = Math.min(visible, found.length);
    summary.textContent = "Showing " + shown + " of " + found.length + " matching files.";
    for (var i = 0; i < shown; i++) {
      var row = found[i].row;
      var item = document.createElement("li");
      var link = document.createElement("a");
      var code = document.createElement("code");
      link.href = "/" + row.path;
      code.textContent = row.path;
      link.appendChild(code);
      item.appendChild(link);
      // The page's own size string, from search-index.json: one formatter, not two.
      item.appendChild(document.createTextNode(" " + row.size));
      if (edgeCase(row)) { item.appendChild(document.createTextNode(" (edge case)")); }
      results.appendChild(item);
    }
    more.hidden = shown >= found.length;
    if (!shown) {
      summary.textContent = "No file matches.";
    }
  }

  function search() {
    if (input.value.trim() && !index) {
      var ready = load();
      show();
      ready.then(show);
    } else {
      show();
    }
  }

  input.addEventListener("input", function () { visible = 20; search(); });
  retry.addEventListener("click", search);
  more.addEventListener("click", function () { visible += 20; show(); });
})();
