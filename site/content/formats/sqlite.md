`sqlite/multi-table-with-fk-indexes-views.sqlite` is the file for a schema inspector: 4 tables, a
foreign key from `orders.person_id` to `people.id`, two indexes, a view named `order_totals` and
an insert trigger, none of which an inspector that lists only tables will show.
`sqlite/people-1000.sqlite` is the flat case, one `people` table of 1,000 rows in 4,096-byte
pages, with no index, view or trigger, and in journal mode DELETE, so there is no `-wal` file to
carry with it.

The foreign key in `sqlite/multi-table-with-fk-indexes-views.sqlite` is declared but not
enforced: SQLite checks foreign keys only on a connection that has run
`PRAGMA foreign_keys = ON`, so a test that expects an order for an unknown person to be refused
passes only after the pragma. `sqlite/multi-table-with-fk-indexes-views.sqlite` also has a
trigger, `orders_audit`, that writes one row to `audit` for each order inserted, and `audit`
starts empty, so one insert should leave exactly one audit row. The view `order_totals` in
`sqlite/multi-table-with-fk-indexes-views.sqlite` lists every person, with a count and total of
zero where there are no orders.

The `products` table of `sqlite/multi-table-with-fk-indexes-views.sqlite` has a text primary
key, which SQLite backs with an automatic index listed in `sqlite_master` with no SQL, so an
inspector that reads the SQL of every index meets NULL. In `sqlite/people-1000.sqlite`,
`birth_date` and `signup_at` are TEXT and `is_active` is an INTEGER, because SQLite has no date
or boolean type, so a tool that maps column types must choose.
