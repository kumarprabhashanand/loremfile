`mp4/non-faststart-720p-5s.mp4` is `mp4/720p-5s.mp4` with the moov atom moved after mdat: the
same 1,974,574 bytes, but a player that streams it cannot show the first frame until the
whole file has arrived, and nothing reports an error.

`mp4/no-audio-720p-5s.mp4` has no audio track at all, for code that assumes every video has
one. `mp4/h264-baseline-720p-5s.mp4` uses the Constrained Baseline profile at level 3.0, which
older devices and some hardware decoders need. `mp4/720p-5s.mp4` uses the High profile at
level 3.1, the default most encoders write.

`mp4/vertical-1080x1920-5s.mp4` is 1080x1920, taller than wide, for players and thumbnailers
that assume landscape. `mp4/360p-5s.mp4` (640x360), `mp4/720p-5s.mp4` (1280x720) and
`mp4/1080p-10s.mp4` (1920x1080) are the same H.264 and AAC, for responsive players and
transcode ladders.

`mp4/1mb.mp4`, `mp4/10mb.mp4` and `mp4/50mb.mp4` are 1280x720 encoded at a flat bitrate to
979,114, 10,062,489 and 50,081,140 bytes, for upload limits and progress bars that need a real
video of a known size.
