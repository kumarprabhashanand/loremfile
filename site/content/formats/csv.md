CSV looks trivial and is not. These files hold the shared synthetic people dataset, the same
records as the JSON, Parquet and SQLite people files, plus the variants that break naive
parsers.

The plain files come in three row counts, `csv/people-10.csv`, `csv/people-1000.csv` and
`csv/people-100k.csv`, each with a header row. Three variants carry ten rows each:
`csv/people-10-semicolon.csv` uses semicolons, as European locales export;
`csv/people-10-quoted-newlines.csv` has a real newline inside a quoted field, which is where
splitting on line breaks goes wrong; `csv/people-10-quoted-commas.csv` puts a comma there
instead, which is where splitting on commas goes wrong; and `csv/people-10-utf8-bom.csv`
starts with a byte-order mark that many readers leave attached to the first column name.

For size limits there are `csv/1mb.csv` and `csv/10mb.csv`, fitted to within 5% of their
nominal size and still a prefix of the same dataset.

Use them to test import dialogs, streaming parsers and spreadsheet uploads. Related formats:
[TSV](/tsv), [JSON](/json), [NDJSON](/ndjson) and [SQL](/sql).
