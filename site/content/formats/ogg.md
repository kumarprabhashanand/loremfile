Ogg Vorbis is the older royalty-free audio codec in the Ogg container. It predates Opus, is
still widely supported, and appears in games, Linux software and web audio.

`ogg/vorbis-30s.ogg` is a 440 Hz sine wave, thirty seconds long, 48 kHz stereo, encoded with
Vorbis at quality 4. The pure tone makes encoder artefacts and playback problems easy to
spot, and the same kind of tone appears across the other audio formats here, so one pipeline
can be compared across codecs.

Use it to test audio players, browser playback, transcoders and upload forms that accept Ogg.
Because an `.ogg` file can hold Vorbis, Opus, FLAC or even Theora video, it is also a good
check that code inspects the stream instead of assuming the codec from the extension.
Related formats: [MP3](/mp3), [FLAC](/flac), and [OGV](/ogv) for Ogg with video.
