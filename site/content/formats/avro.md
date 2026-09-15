Apache Avro is a row-oriented format common in Kafka pipelines and Hadoop jobs. Every Avro
data file embeds the writer's schema in its header, so a reader can decode the records
without a separate schema registry. `avro/people-1000.avro` holds 1,000 rows of the shared
people dataset, deflate-compressed.

Because the schema travels with the data, this file is useful for testing schema resolution:
read it with a different reader schema and check how added, removed or renamed fields are
handled. Because the rows are the same records as the CSV, JSON, Parquet and Arrow people
files, you can also check that a pipeline produces the same result whichever format it reads.

Deflate is one of the codecs the Avro specification requires every implementation to
support, so the file should open in any conforming reader. Related formats:
[Parquet](/parquet) for columnar storage and [Arrow](/arrow) for in-memory interchange.
