JSON is the common language of APIs, and most JSON parsers are fine until they meet a number,
a string or a depth they did not expect. These files cover the everyday case and the awkward
ones.

`json/people-10.json` and `json/people-1000.json` are arrays of people objects from the
shared synthetic dataset, pretty-printed with two-space indentation; the same records appear
in the CSV, Parquet and SQLite people files.

`json/all-types.json` exercises every scalar shape worth testing: null, booleans, negative
zero, exponents, integers beyond 2^53 and 2^63, Unicode escapes, a surrogate pair and empty
containers. JavaScript's `JSON.parse` silently loses precision on the large integers, which
is what the file is for. `json/nested-100-levels.json` nests an object 100 levels deep, for
parsers with a recursion limit.

For size limits, `json/1mb.json` and `json/10mb.json` hold people objects fitted to within 5%
of their nominal size. Related formats: [NDJSON](/ndjson), [YAML](/yaml), [TOML](/toml) and
[XML](/xml).
