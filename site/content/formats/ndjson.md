NDJSON, newline-delimited JSON, puts one complete JSON object on each line. Stream
processors, log shippers and bulk APIs prefer it because a reader can handle one record at a
time without loading the whole file, and a truncated file loses only its last line.

`ndjson/people-1000.ndjson` holds 1,000 people objects from the shared synthetic dataset, one
compact object per line, the same records as the JSON, CSV and Parquet people files. That
makes it easy to compare a streaming import against a batch import of the same data.

Use it to test bulk-import endpoints, streaming parsers, line-based tools such as `jq` and
`split`, and upload forms that accept JSON lines. A common bug to look for is a parser that
reads the file as one JSON document and fails on the second line. Related formats:
[JSON](/json) and [log files](/log).
