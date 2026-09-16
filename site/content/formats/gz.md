A gzip file is a single compressed stream rather than an archive. There is no entry list to
enumerate and no directory structure inside it, which is the distinction tools most often get
wrong when they assume anything compressed can be listed.

`gz/lorem-1mb.txt.gz` compresses exactly 1,000,000 bytes of Lorem Ipsum, so the ratio you
measure is that of ordinary prose. `gz/multi-member-3.gz` is the more interesting case: three
gzip members concatenated into one file. A correct reader decompresses to the end and returns
all three; a naive one stops after the first member and silently returns a third of the data,
which is a bug that can sit undetected for years.

Use them to test decompression, `Content-Encoding` handling, streaming readers and log
ingestion pipelines. For the same payload in other stream formats see [BZIP2](/bz2),
[XZ](/xz) and [ZSTD](/zst); for the archive that usually wraps them, [TAR](/tar).
