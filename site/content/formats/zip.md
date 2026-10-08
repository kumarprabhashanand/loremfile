Zip is the archive format everything claims to support, and the one with the most ways to go
wrong. These files cover what extractors actually have to handle.

`zip/3-text-files.zip` is the ordinary case: three deflated text files with fixed timestamps.
`zip/nested-directories.zip` has four entries in a three-level tree, for extractors that must
create directories as they go. `zip/empty.zip` is a 22-byte end-of-central-directory record
and nothing else — valid, and rejected by plenty of readers.
`zip/mixed-fixtures.zip` packs four published fixtures, a PDF, a PNG, a CSV and a JSON file,
read from the bytes that were actually published, so what you extract can be compared against
the originals. `zip/aes256-password-loremfile.zip` is encrypted with the password
`loremfile`, published on purpose because an encrypted archive nobody has the password to is
useless as a fixture.

For size limits there are `zip/1mb.zip`, `zip/10mb.zip` and `zip/100mb.zip`, each a single
incompressible member so the archive's size is honest rather than padded.

`zip/zip64-70000-empty-files.zip` forces ZIP64 through 70,000 central-directory entries,
past the 65,535 limit, while every member is empty. It occupies 7,420,098 bytes without a
large expanded payload. The validator checks the ZIP64 end record and locator against the
members it actually reads, so a truncated count cannot pass as a complete archive.

Related formats: [TAR](/tar), [GZIP](/gz) and [7z](/7z).
