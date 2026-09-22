WebM is the royalty-free video format browsers play natively: a restricted Matroska container
holding VP8, VP9 or AV1 video with Vorbis or Opus audio. These clips use ffmpeg's synthetic
test pattern and a 440 Hz tone, with no third-party footage.

`webm/720p-5s-vp9.webm` is 1280x720 at 30 frames per second for five seconds, VP9 video with
Opus audio. It pairs with `mp4/720p-5s.mp4`, the same picture size, frame rate and length in
H.264 and AAC, so a player, thumbnailer or upload pipeline can be compared across the two
formats that between them cover nearly every browser.

Use it to test `<video>` playback, transcoders, thumbnail generation and upload forms that
accept the `video/webm` media type. It is also a check that code reads the codecs from the
stream rather than trusting the extension: a `.webm` file can carry VP8, VP9 or AV1, and
each needs a different decoder. Related formats: [MP4](/mp4), [MKV](/mkv) and [OGV](/ogv).
