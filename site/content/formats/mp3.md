`mp3/sine-440hz-3s.mp3` is the baseline, 128 kbps stereo at 48 kHz, and its measured 3,024 ms
are three seconds plus the padding MP3 adds to fill whole frames, which a duration check that
expects exactly three seconds gets wrong.

`mp3/stereo-lr-5s.mp3` measures 440 Hz in the left channel and 880 Hz in the right, so a
pipeline that swaps or downmixes channels changes which tone comes out where.
`mp3/silence-5s.mp3` is a valid MP3 with no tone in either channel, for code that treats
silence as a failed decode.

`mp3/with-id3v2-tags-3s.mp3` carries ID3v2 tags and a 100x100 PNG cover, which ffprobe
reports as a video stream: an upload validator that refuses audio with a video stream refuses
an ordinary tagged MP3. `mp3/sine-440hz-30s.mp3` runs 30,024 ms, long enough to test seeking
and scrubbing.

`mp3/1mb.mp3` is 996,116 bytes at a constant 128 kbps, so its 62,232 ms follow from its size.
`mp3/10mb.mp3` is 9,950,996 bytes and 621,912 ms of the same stream, for upload limits and
players that must stream rather than load.
