FLAC compresses audio without losing anything: decode it and you get back exactly the samples
that went in. That makes it the format to reach for when you need a file that is both
compressed and bit-identical to its source, for example when testing that a pipeline does
not re-encode audio it should only copy.

`flac/sine-440hz-30s.flac` is a 440 Hz sine wave, thirty seconds long, 48 kHz stereo. A pure
tone compresses well without loss and is easy to verify: the spectrum of the decoded audio
shows a single clean peak, and any processing that adds distortion or noise shows up beside
it.

Use it to test audio players, tag editors, transcoders that should preserve quality, and
upload forms that list FLAC as accepted. For the uncompressed equivalent see [WAV](/wav); for
lossy versions of the same tone see [MP3](/mp3) and [OGG](/ogg).
