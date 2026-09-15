Matroska is the container that will hold almost anything: any codec, several audio and
subtitle tracks, chapters and attachments. `mkv/720p-5s.mkv` keeps it simple on purpose, with
H.264 video and AAC audio, the same codecs as the MP4 fixture.

That makes the container the only variable. If a player, thumbnailer or upload validator
handles `mp4/720p-5s.mp4` and fails on this file, the problem is its Matroska support, not
the codec. The clip is 1280x720 at 30 frames per second, five seconds long, and generated
synthetically. WebM is Matroska underneath too, restricted to royalty-free codecs.

Use it to test media servers, transcoding pipelines, browser playback, which varies because
not every browser plays Matroska, and format sniffers that recognise the EBML header.
Related formats: [MP4](/mp4) and [MOV](/mov) for the same codecs in other containers.
