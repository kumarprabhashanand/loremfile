OGV is Ogg with video: Theora video and Vorbis audio, the older royalty-free stack. It
predates VP9 and WebM but is still what some toolchains emit, and it is a useful negative
control when a pipeline claims to support royalty-free video.

`ogv/720p-5s.ogv` is 1280x720 at 30 frames per second, five seconds long, generated
synthetically with no real footage. Several browsers and hardware decoders no longer play
Theora, so this file shows how a player or upload validator behaves with a valid video it may
not be able to decode, which is a different failure from a corrupt one.

Use it to test media servers, transcoding pipelines that must convert legacy video, and
format sniffers that must look at the codec inside an Ogg container rather than at the
extension. Related formats: [MP4](/mp4), and [OGG](/ogg) for audio in the same container.
