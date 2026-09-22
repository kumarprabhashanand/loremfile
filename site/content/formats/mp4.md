MP4 with H.264 video and AAC audio is the format every player and upload form accepts. These
clips use synthetic test patterns and a 440 Hz tone, with no third-party footage, and every
file is faststart, so the index comes first and progressive playback works.

`mp4/720p-5s.mp4` is the default if you need just one file: 1280x720 at 30 frames per second
for five seconds. `mp4/360p-5s.mp4` is the small one, 640x360, for quick tests, and
`mp4/vertical-1080x1920-5s.mp4` is portrait, the shape phones record and social apps expect.

Two files target specific assumptions. `mp4/no-audio-720p-5s.mp4` has no audio track at all,
for code paths that assume every video has one, and `mp4/h264-baseline-720p-5s.mp4` uses the
constrained Baseline profile that old devices and some hardware decoders need.

For size limits, `mp4/1mb.mp4`, `mp4/10mb.mp4` and `mp4/50mb.mp4` reach their sizes through
two-pass encoding at a flat bitrate rather than padding, so the sizes are honest.
`mp4/1080p-10s.mp4` is full HD for ten seconds. Related formats: [MKV](/mkv), [MOV](/mov) and
[MP3](/mp3).
