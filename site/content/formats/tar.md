Tar is the archive format of the Unix world, and unlike zip it has no central directory: a
reader walks the file from the beginning, one header at a time. That difference shows up as
soon as something has to seek, stream or truncate.

`tar/3-text-files.tar` is three small Lorem Ipsum text files uncompressed, every entry owned by
uid 0 with a fixed timestamp. The same three files are published compressed two ways:
`tar/3-text-files.tar.gz`, the `.tar.gz` most tooling means when it says "a tarball", and
`tar/3-text-files.tar.xz` for the smaller, slower option.

Fixed ownership and timestamps are the reason these are useful as fixtures. A tar built on your
machine embeds your user, your group and the moment you built it; these embed none of that, so
the checksum is stable and the archive reveals nothing about where it came from.

Use them to test extraction, streaming readers and build caches. Related formats:
[ZIP](/zip), [GZIP](/gz) and [7z](/7z).
