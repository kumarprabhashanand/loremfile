An xz file is a single compressed stream rather than an archive: no container, no entry list,
one payload in and one stream out. It compresses harder than gzip and takes longer doing it,
which is why it turns up around software distribution and large logs.

`xz/lorem-1mb.txt.xz` compresses exactly 1,000,000 bytes of Lorem Ipsum, so the ratio you
measure is that of ordinary prose rather than of random noise or a file padded to a round
number. That makes it a realistic figure for a progress bar, a quota calculation or a
back-of-the-envelope estimate of what compression will buy you.

Because it is a stream and not an archive, it is also a good test of whether your code knows
the difference — plenty of tools try to list the contents of an xz file and fail confusingly.

Use it to test decompression, streaming readers and package handling. Related formats:
[GZIP](/gz), [BZIP2](/bz2), [ZSTD](/zst) and [TAR](/tar), the container these usually wrap.
