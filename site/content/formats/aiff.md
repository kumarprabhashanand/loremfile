AIFF is Apple's uncompressed audio container and the byte-order twin of WAV: the same kind
of PCM samples, stored big-endian instead of little-endian. A reader that assumes
little-endian samples does not crash on an AIFF file; it plays loud noise. That silent
failure is what `aiff/3s.aiff` exists to catch.

The file holds three seconds of a 440 Hz sine wave as 44.1 kHz, 16-bit stereo PCM. Because
the signal is a pure tone, a byte-order mistake is unmistakable in a waveform view, and a
correct decoder produces a clean, steady pitch.

Use it to test audio libraries, format sniffers that must tell AIFF from WAV by its `FORM`
header, and converters that move audio between Apple and Windows tooling. Compare it with the
little-endian [WAV](/wav) files, or with [FLAC](/flac) for the same kind of audio compressed
without loss.
