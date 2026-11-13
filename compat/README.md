# compat/

How each runtime's standard library reads our files. The scoreboard is at
<https://loremfile.dev/compat>; the reasoning is `docs/07-website.md` §8 and ADR-033. This file is the
adapter contract and how to add a reader.

Nothing here imports `src/loremfile`, runs in the toolchain image, touches the lock or can fail a
deploy. The runtimes are the latest supported ones, their versions recorded and never pinned.

## Layout

| Path | What it is |
|---|---|
| `runtimes.yaml` | Versions to run, each with the page that lists them as supported and the date. |
| `readers.yaml` | The corpus rules, and each reader: id, runtime, formats, the properties it reports, two controls. |
| `adapters/<runtime>/` | One adapter per runtime: a program that opens one file with one reader. |
| `harness/` | Standard-library Python: fetch, run, compare, write. `python -m harness {fetch,run,merge,check}` from this directory. |
| `results/` | `_run.json` (run id, date, resolved runtime versions) and one `{format}.json` each, keys sorted, no timestamps. Written by the workflow, never by hand. |

`runtimes.yaml` and `readers.yaml` are written as JSON, which YAML accepts: the harness reads them
with the standard library and the site build reads the same bytes with PyYAML.

## The adapter contract

    adapter <reader-id> <path> [--password P] [--delimiter D]

It prints exactly one JSON object and exits 0. Anything else is `crashes`.

    {"outcome":"reads","props":{"entries":3,"uncompressed_bytes":1440}}
    {"outcome":"refuses","error_type":"wave.Error","error":"unknown format: 65534"}
    {"outcome":"no-reader"}

- Read the whole file, not the header: every archive member's bytes, every audio frame, every
  pixel, every row. A reader that stops early is the finding.
- Report only the properties the reader gives natively, under the manifest's own names. Compute
  nothing clever beyond the named exceptions below. The harness compares only names present on both
  sides.
- Default settings, except what the harness passes: `--password` for a file whose manifest says
  `encrypted`, and `--delimiter` (the manifest's) for CSV.
- Never write an archive member to disk. `error` is the first line, 200 characters at most.
- Open the file the way the reader's own documentation shows. Where it takes text, read it as UTF-8.

The names, from the manifest: zip and tar `entries`, `directories`, `uncompressed_bytes`; gz
`uncompressed_bytes`, `members`; wav `channels`, `sample_rate`, `bit_depth`, `duration_ms`; jpg, png
and gif `width`, `height`, `frames`; json `top_type`, `items`; csv `rows`, `columns`; xml
`root_element`; pem and der `subject_cn`, `issuer_cn`, `serial`, `dns_names`. An adapter reports
`members` and `frames` only where its reader exposes them with default settings.

The harness judges, not the adapter. `reads` means no error and every property both sides hold is
equal; `differs` means at least one is not. There are three named exceptions, listed in
`readers.yaml` under `scope.exceptions` and shown on the page: a 1 ms tolerance on `duration_ms`;
for CSV, the expected `rows` is the manifest's plus one when it says `has_header`, because the
header is a record to a reader and not a data row; and a root name in Clark notation,
`{namespace}local`, is reduced by the adapter to its local name before it is reported as
`root_element`, the form the manifest holds (the manifest lists the namespace URIs apart, under
`namespaces`). A reader may report the namespace as its own property, `root_namespace`, which is
never compared and is not `root_element`.

## Outcomes

`reads`, `differs`, `refuses`, `crashes` (the process died, printed no result, or passed 30
seconds), `no-reader` (the runtime's standard library has no reader for the format) and `not-run`
(the runtime, adapter or fetch could not be set up; never counted). For an `edge/` file whose own
`outcome` is `must-fail`, `refuses` is the expected cell and `reads` the notable one.

## Controls

Every reader names two in `readers.yaml`: a file it must read (outcome `reads`) and the broken
twin of that file, empty or cut in half, that it must not read. Not reading means the answer is not
`reads`, or is `reads` with properties other than the intact file's: a reader that reports the same
for an empty file as for a real one is not reading. If either control misses on a runtime version,
that reader's cells there are `not-run`.

## Adding a reader

1. Add it to `adapters/<runtime>/` and to `readers.yaml` with its formats, properties and controls.
2. Run it against the corpus: `python -m harness fetch --out ../work`, then
   `python -m harness run --runtime <runtime> --version <v> --work ../work --out ../parts`.
3. Open a pull request. `compat.yml` runs on `compat/**` and the results in the pull request come
   from that run: `gh run download <id> -n compat-results`, never from a laptop.
