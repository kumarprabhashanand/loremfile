SQL dumps are how data moves between databases, and they break on vendor-specific syntax:
backtick quoting, `AUTO_INCREMENT`, `SERIAL` or bracketed identifiers.
`sql/people-1000-inserts-portable.sql` avoids all of it.

It holds one `CREATE TABLE` statement and 1,000 `INSERT` statements for the shared synthetic
people dataset, using only syntax that every major database accepts, so the same file loads
into SQLite, PostgreSQL and MySQL alike. The rows are the same records as the CSV, JSON and
SQLite people files.

Use it to test database import tools, migration scripts, SQL editors that preview large
files, and upload forms that accept `.sql` files. One statement per row also makes it a
realistic test of import speed with and without a surrounding transaction. Related formats:
[CSV](/csv), [JSON](/json) and the ready-made [SQLite](/sqlite) database.
