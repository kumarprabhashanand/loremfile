`mkv/720p-5s.mkv` carries H.264 video and AAC audio at 1280x720, the codecs of
`mp4/720p-5s.mp4`, so between the two the container is the only variable: a player,
thumbnailer or upload validator that handles the MP4 and fails on the MKV has a Matroska
problem, not a codec problem. `mkv/vp9-opus-720p-5s.mkv` turns that round, with the VP9 and
Opus of `webm/720p-5s-vp9.webm` in general Matroska, for sniffers that tie VP9 to the .webm
extension or Matroska to H.264.

`mkv/multi-audio-2-tracks-720p-5s.mkv` has two audio tracks, measured at 440 Hz and 880 Hz,
so a converter or player that only ever takes the first track is caught by the tone it plays.
`mkv/with-subtitles-720p-5s.mkv` adds an SRT (`subrip`) subtitle track, which a remux that
drops or mis-maps text tracks loses. `mkv/with-chapters-720p-5s.mkv` adds 3 chapters to its
Matroska chapter list, for seek menus and chapter navigation that need something to show.
