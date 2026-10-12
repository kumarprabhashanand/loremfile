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

  function load() {
    if (!loading) {
      loading = fetch(input.dataset.index)
        .then(function (response) { return response.json(); })
        .then(function (rows) { index = rows; });
    }
    return loading;
  }

  function show(query) {
    results.textContent = "";
    if (!query || !index) { return; }
    var words = query.toLowerCase().split(/\s+/);
    var shown = 0;
    for (var i = 0; i < index.length && shown < 20; i++) {
      var row = index[i];
      var text = (row.path + " " + row.description).toLowerCase();
      if (words.every(function (word) { return text.indexOf(word) !== -1; })) {
        var item = document.createElement("li");
        var link = document.createElement("a");
        var code = document.createElement("code");
        link.href = "/" + row.path;
        code.textContent = row.path;
        link.appendChild(code);
        item.appendChild(link);
        // The page's own size string, from search-index.json: one formatter, not two.
        item.appendChild(document.createTextNode(" " + row.size));
        results.appendChild(item);
        shown++;
      }
    }
    if (!shown) {
      var none = document.createElement("li");
      none.textContent = "No file matches.";
      results.appendChild(none);
    }
  }

  input.addEventListener("input", function () {
    var query = input.value.trim();
    load().then(function () { show(query); });
  });
})();
