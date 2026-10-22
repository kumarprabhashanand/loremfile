`zip/zip64-70000-empty-files.zip` holds 70,000 entries, more than a classic ZIP entry count can
hold, so it needs ZIP64: a reader that truncates the count loses entries without an error.
`zip/empty.zip` is 22 bytes and 0 entries, the empty archive many readers refuse although it
is valid.

`zip/aes256-password-loremfile.zip` is encrypted with 3 entries and opens with the password
loremfile, published so the test can pass. `zip/nested-directories.zip` holds 4 entries in a
three-level tree, for extractors that must create directories. `zip/mixed-fixtures.zip` holds 4
published files of different types, 9,838 bytes uncompressed, and `zip/3-text-files.zip` is 3
small text files, the plain baseline.

`zip/1mb.zip`, `zip/10mb.zip` and `zip/100mb.zip` each hold 1 member of incompressible noise in
999,421, 9,993,166 and 99,030,316 bytes, so the archive is the size of its contents, for upload
limits and extractors that stream.
