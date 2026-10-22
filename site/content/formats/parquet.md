`parquet/people-1000.parquet`, `parquet/people-1000-zstd.parquet` and
`parquet/people-1000-gzip.parquet` hold the same 1,000 rows in 14 columns and differ only in
compression: snappy at 114,469 bytes, zstd at 86,695 and gzip at 83,002. A reader built
without zstd reads the footer of `parquet/people-1000-zstd.parquet` and then fails on its
data, so test every codec your users may send.

`parquet/people-1000-10-row-groups.parquet` holds the same rows in 10 row groups where
`parquet/people-1000.parquet` has 1, at 174,780 bytes: a reader that only ever reads the first
row group returns a tenth of the rows and raises nothing.

`parquet/nested-types.parquet` reshapes the same 1,000 people into nested columns, typed
`int32`, `struct<first: string, last: string>`,
`struct<street: string, city: string, country: string>`, `map<string, string ('contacts')>`
and `list<element: string>`, where `parquet/people-1000.parquet` nests only `tags`. A loader
that flattens everything to scalar columns has nowhere to put the structs or the map in
`parquet/nested-types.parquet`.

`parquet/people-100k.parquet` keeps the flat layout with 100,000 rows in 9,756,012 bytes, for
reads that should stream rather than load the whole file. Its rows are the ones in
`csv/people-100k.csv`, so a pipeline can be checked for identical results whichever it reads.
