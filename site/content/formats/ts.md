The MPEG-2 transport stream is the container of broadcast television and of HLS segments. It
is built for streams that can be joined at any point: data travels in fixed 188-byte packets,
so a demuxer can synchronise mid-stream.

`ts/720p-5s.ts` is 1280x720 at 30 frames per second, five seconds long, with H.264 video and
AAC audio in a transport stream. It is offered on its own so a demuxer or player can be tested
without a playlist, and it uses the same codecs as the [HLS](/hls) segments and the
[MP4](/mp4) fixtures.

Use it to test media servers, transcoders, stream analysers and upload forms that accept
broadcast recordings. It is also a MIME check: transport streams are served as `video/mp2t`,
and the `.ts` extension is shared with TypeScript source files, so code that classifies by
extension alone can get it wrong. The file is generated synthetically, with no real footage.
