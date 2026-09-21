AAC is the lossy codec behind most streaming audio. These files carry it as a bare ADTS
stream, with no MP4 container around the frames: the shape broadcast feeds and HLS audio
arrive in. That makes `aac/adts-30s.aac` a good test of whether a decoder can find frame
boundaries on its own, or quietly expects the box structure of an M4A file.

The file is a 440 Hz sine wave, thirty seconds long, 48 kHz stereo at 128 kbps. A pure tone
is easy to check by ear and by spectrum: any pitch shift, dropout or channel problem is
obvious.

Use it to test upload validation that inspects a file's first bytes, players that must
stream rather than seek, and transcoders that need to wrap raw AAC in a container. For the
same audio inside MP4, see [M4A](/m4a); for the transport stream that often carries ADTS
audio, see [TS](/ts).
