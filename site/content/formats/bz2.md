A bzip2 file is a single compressed stream, not an archive. There is no container, no entry
list and no filename inside it: one payload goes in, one stream comes out. Tools that treat
every compressed file as an archive get this wrong, which is exactly what makes it useful.

`bz2/lorem-1mb.txt.bz2` compresses exactly 1,000,000 bytes of Lorem Ipsum, so the compression
ratio you measure is the ratio of ordinary prose rather than of random noise or of a file
padded to a round size. Because the input is text, the output is substantially smaller than
the input, and the difference is a realistic figure to show in a progress bar or a quota
calculation.

Use it to test decompression paths, content-encoding handling, and anything that has to tell a
compressed stream apart from an archive it can list. Related formats: [GZIP](/gz),
[XZ](/xz), [ZSTD](/zst) and [TAR](/tar), which is the container the streams usually wrap.
