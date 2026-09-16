Zstandard is the modern compression stream: close to gzip's ratio at far higher speed, which
is why it has spread quickly through storage systems, package managers and log pipelines. Like
gzip it is a stream, not an archive — there is no entry list to enumerate.

`zst/lorem-1mb.txt.zst` compresses exactly 1,000,000 bytes of Lorem Ipsum, so the ratio you
measure is the one ordinary prose gives you rather than a figure distorted by random noise or
padding.

It is the newest of the four stream formats published here, and therefore the one your
dependencies are most likely to lack: a runtime without zstd support fails in a different and
usually less helpful way than one that simply cannot open a file. That is worth finding out
deliberately rather than in production.

Use it to test decompression, content-encoding negotiation and streaming readers. Related
formats: [GZIP](/gz), [BZIP2](/bz2), [XZ](/xz) and [TAR](/tar).
