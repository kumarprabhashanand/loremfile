Apache Parquet is the columnar format of data lakes and analytics engines. It stores each
column separately and compresses it, so queries read only the columns they need.

`parquet/people-1000.parquet` and `parquet/people-100k.parquet` hold 1,000 and 100,000 rows
of the shared synthetic people dataset, snappy-compressed, each in a single row group. They
contain the same records as the CSV, JSON, Arrow and Avro people files, so a pipeline can be
checked for identical results whichever format it reads.

The two sizes test different things. The small file is quick to inspect with any Parquet
reader; the large one is big enough to measure column pruning, filtering and memory use, and
to test upload paths that stream rather than buffer. A single row group keeps the layout
simple, so row-group statistics are easy to reason about.

Use them with DuckDB, pandas, Spark or cloud query services. Related formats:
[Arrow](/arrow), [Avro](/avro), [CSV](/csv) and [SQLite](/sqlite).
