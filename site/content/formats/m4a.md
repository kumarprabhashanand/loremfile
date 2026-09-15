M4A is AAC audio in an MP4 container, the file Apple devices produce and many streaming
services deliver. Unlike a bare ADTS stream, the container carries an index of the audio, so
players can seek and show a duration before reading the whole file.

`m4a/aac-30s.m4a` is a 440 Hz sine wave, thirty seconds long, 48 kHz stereo AAC at 128 kbps.
The same kind of tone appears across the audio formats here, which makes it easy to compare
how one pipeline handles several containers and codecs.

Use it to test audio players and seeking, metadata readers, transcoders, and upload forms
that accept M4A. It also checks MIME handling: the file is served as `audio/mp4`, and code
that expects `audio/x-m4a`, or looks only at the extension, may reject it. Related formats:
[AAC](/aac) for the same codec without a container, and [MP3](/mp3).
