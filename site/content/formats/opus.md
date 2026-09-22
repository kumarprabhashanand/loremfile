Opus is the royalty-free audio codec the IETF standardised in RFC 6716, and the one browsers,
WebRTC and voice applications settled on. A `.opus` file is Opus inside an Ogg container, as
RFC 7845 specifies.

`opus/30s.opus` is a 440 Hz sine wave, thirty seconds long, stereo, encoded at 96 kbps. The
same kind of tone appears across the other audio formats here, so one pipeline can be
compared across codecs.

One gotcha is built into the format: Opus decoders produce 48 kHz output, and tools report
48 kHz whatever rate the source had. The original rate survives only as an informational
header field. Code that expects the source rate back, or that assumes 44.1 kHz, gets this
file wrong in a way a quick listen will not reveal.

Use it to test browser playback, transcoders, waveform renderers, audio upload forms and
handling of the `audio/opus` media type. It is also a check that code reads the codec from
the stream: an Ogg file can carry Opus, Vorbis or FLAC. Related formats: [Ogg Vorbis](/ogg),
[MP3](/mp3) and [M4A](/m4a).
