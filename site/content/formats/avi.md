`avi/640x480-5s.avi` is for code that assumes video means H.264: it carries MPEG-4 Part 2
where `mp4/720p-5s.mp4` carries H.264, so a decoder, thumbnailer or transcoder that handles the
MP4 and fails on this file has a codec assumption, not a container problem. The audio of
`avi/640x480-5s.avi` is MP3, mono at 48 kHz, a 440 Hz tone with one MP3 frame to each chunk.

`avi/640x480-5s.avi` keeps its `idx1` index after the media data, so a reader that seeks has to
reach the end of the file first, and a download cut short has no index at all.
`avi/640x480-5s.avi` also pads its header lists with `JUNK` chunks and holds a `vprp` chunk,
which a parser has to skip by length, not reject.

The second video chunk of `avi/640x480-5s.avi` is empty, a frame slot with no data, so a
demuxer that takes an empty chunk for the end of the stream stops after one frame. At 640x480
and 30 frames per second, `avi/640x480-5s.avi` runs 5.04 seconds in 1,734,596 bytes.
