This is a sample WAV file: uncompressed PCM audio in the CD format, free to hotlink or
download.

<!-- file: wav/sine-440hz-3s-44k-16bit-stereo.wav -->

WAV is the format most audio software assumes by default.
`wav/sine-440hz-3s-44k-16bit-stereo.wav` is a sine tone at 44.1 kHz, 16-bit stereo, behind the
canonical 44-byte header: the simple layout that hand-written readers expect and that extra
chunks break.

`wav/10mb.wav` is exactly 10,000,000 bytes: the same 44-byte header plus 2,499,989 frames of the
same kind of audio. Uncompressed audio is the one format where a byte count is arithmetic
rather than an estimate. Each stereo frame takes four bytes, so the duration follows from the
size: just under 57 seconds.

`wav/sine-440hz-3s-48k-24bit-stereo.wav` is 48 kHz, 24-bit stereo, and its header is 68 bytes: it uses
the extensible format tag, whose longer `fmt ` chunk moves the samples further in. A reader
that skips a fixed 44 bytes instead of walking the chunks plays the end of the header as audio.

Use them to test audio players, upload size limits with a real media file, speech and audio
processing pipelines, and converters. Compare them with the big-endian [AIFF](/aiff) file, or
with [FLAC](/flac) and [MP3](/mp3) for compressed versions of the tone.
