SQLite is the database in a file, and the format behind countless mobile apps and desktop
tools. There are two databases here.

`sqlite/people-1000.sqlite` is a single table holding 1,000 rows of the shared synthetic
people dataset. It uses a 4,096-byte page size and the DELETE journal mode, and was vacuumed,
so the file is byte-stable.

`sqlite/multi-table-with-fk-indexes-views.sqlite` is what a schema inspector should be tested
against: four tables, a foreign key from orders to people, two indexes, a view that
aggregates order totals and an insert trigger. A tool that lists only tables, or loses the
foreign key when exporting, shows it immediately.

Use them to test database browsers, ORM introspection, backup and upload paths, and code that
recognises a database by the `SQLite format 3` header at the start of the file. Related
formats: [SQL](/sql), [CSV](/csv) and [Parquet](/parquet).
