WAV is uncompressed PCM audio, the format most audio software assumes by default. These files
use the canonical 44-byte header, the simple layout that hand-written readers expect and that
extra chunks break.

`wav/sine-440hz-3s-44k-16bit-stereo.wav` is three seconds of a 440 Hz sine at 44.1 kHz,
16-bit stereo: the CD format, and what most software assumes a WAV is.

`wav/10mb.wav` is exactly 10,000,000 bytes: the 44-byte header plus 2,499,989 frames of the
same kind of audio. Uncompressed audio is the one format where a byte count is arithmetic
rather than an estimate. Each stereo frame takes four bytes, so the duration follows from the
size: just under 57 seconds.

Use them to test audio players, upload size limits with a real media file, speech and audio
processing pipelines, and converters. Compare them with the big-endian [AIFF](/aiff) file, or
with [FLAC](/flac) and [MP3](/mp3) for compressed versions of the tone.
