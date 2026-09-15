AVI is an old Microsoft container that still turns up in upload forms, archives and camera
exports. Real AVI files rarely carry H.264. They carry MPEG-4 Part 2 video, the codec family
of Xvid and DivX, often with MP3 audio. `avi/640x480-5s.avi` uses exactly that combination,
so it tests whether a decoder or thumbnailer quietly assumes H.264.

The clip is 640x480 at 30 frames per second and five seconds long. Like every video here it
is generated synthetically, with no real footage, so it is safe to publish, share and commit
to a test suite.

Use it for upload validation, transcoding pipelines, media servers that must accept legacy
files, and format sniffers that recognise the `RIFF` header with an `AVI` form type. For a
modern container with comparable content, see [MP4](/mp4) or [MKV](/mkv).
