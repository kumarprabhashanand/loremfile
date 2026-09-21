MP3 is still the audio format everything accepts. These files come from ffmpeg's synthetic
sources, and every one has a Xing header, so seeking and duration are exact rather than
estimated.

`mp3/sine-440hz-3s.mp3` is the smallest useful sample, three seconds of a 440 Hz sine at
128 kbps; its measured duration is 3,024 ms because an MP3 frame holds 1,152 samples and the
encoder rounds up to a whole frame. `mp3/sine-440hz-30s.mp3` is long enough to test seeking.
`mp3/stereo-lr-5s.mp3` plays 440 Hz in the left channel and 880 Hz in the right, so swapped
or downmixed channels are obvious, and `mp3/silence-5s.mp3` is five seconds of digital
silence, for code that treats silence as failure.

`mp3/with-id3v2-tags-3s.mp3` carries ID3v2.3 tags, with a title, artist, album, year and PNG
cover image. For size limits, `mp3/1mb.mp3` and `mp3/10mb.mp3` use a constant 128 kbps.
Related formats: [WAV](/wav), [FLAC](/flac), [OGG](/ogg) and [M4A](/m4a).
