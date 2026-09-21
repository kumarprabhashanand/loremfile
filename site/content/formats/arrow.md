Apache Arrow's IPC file format stores columnar data the way Arrow holds it in memory, so a
reader can map the file and use it without parsing. `arrow/people-1000.arrow` contains 1,000
rows of the shared synthetic people dataset, the same records as the CSV, JSON, Parquet and
Avro people files, in a single record batch.

Two details matter when testing. First, this is the IPC *file* format, with a footer, not
the streaming format; the two share most of their bytes but are opened by different APIs,
and a reader pointed at the wrong one fails. Second, because the rows match the other people
fixtures, you can load the same data from several formats and compare the results column by
column.

Use it for data pipeline tests, schema inspection, and checks that a service accepting Arrow
data handles a file where it might expect a stream. Related formats: [Parquet](/parquet) and
[Avro](/avro).
