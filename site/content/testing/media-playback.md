Playback bugs hide in how a file is laid out and served as much as in its codec. These files
separate the two: the same kind of video in a different order, a different codec, a missing
track, a second rendition. All of them are served with byte-range support and open CORS, so a
player on any origin can seek them.

## Where the index sits

<!-- file: mp4/720p-5s.mp4 -->

The index (`moov`) comes before the media (`mdat`), so a player can start and seek after
fetching the first bytes.

<!-- file: mp4/non-faststart-720p-5s.mp4 -->

The same resolution, duration and codecs with `moov` at the end. A progressive player has to
reach the end of the file before it can play, which a range request does quickly and a
server without range support turns into a full download.

## Seeking and range requests

<!-- file: mp4/50mb.mp4 -->

Two minutes of 720p, large enough that a seek which downloads from the start shows plainly in
the network panel.

<!-- file: mp3/sine-440hz-30s.mp3 -->

Thirty seconds of MP3 with a Xing header, so a seek by time lands where it should rather
than where an estimate from the file size puts it.

<!-- file: bin/incrementing-1mb.bin -->

Bytes 00 to FF repeating, with no decoder in the way. The first byte of a range response is
the requested offset modulo 256, so an off-by-one range shows at once.

## Codecs and tracks

<!-- file: mp4/h264-baseline-720p-5s.mp4 -->

H.264 in the constrained profile that older devices and some hardware decoders need. The
profile and level above are read from the stream, not from the encoder settings.

<!-- file: webm/720p-5s-vp9.webm -->

VP9 video with Opus audio in WebM, the royalty-free pair: the file for testing what a player
does when it is handed something other than H.264.

<!-- file: mp4/no-audio-720p-5s.mp4 -->

No audio track at all. Code that builds an audio graph or shows a volume control without
checking fails here, or shows a control that does nothing.

<!-- file: mp4/vertical-1080x1920-5s.mp4 -->

Portrait video. Players and thumbnailers that assume landscape crop it or shrink it into a
strip.

<!-- file: wav/sine-440hz-3s-48k-24bit-stereo.wav -->

24-bit audio behind a 68-byte header. A player that skips a fixed 44 bytes plays the end of
the header as audio.

<!-- file: opus/30s.opus -->

Opus decodes at 48 kHz whatever rate the source had. A player or analyser that expects the
original rate back gets the duration or the pitch wrong.

## Adaptive streaming

<!-- file: hls/multi-bitrate/master.m3u8 -->

Two renditions, 360p and 720p, each with a BANDWIDTH measured from its segments. Throttle the
connection and an adaptive player should step down to 360p, then back up when it recovers.

The same files sit with the rest of their formats on [MP4](/mp4), [WebM](/webm),
[HLS](/hls) and [WAV](/wav).
