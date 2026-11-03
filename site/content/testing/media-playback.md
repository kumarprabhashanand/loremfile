Playback bugs come from how a file is laid out and served as much as from its codec. These
files help you tell which one you have. Some hold the same video in a different order. Some
change the codec, drop a track or add a second rendition. All of them are served with
byte-range support and open CORS, so a player on any origin can seek them.

## Where does the index sit?

<!-- file: mp4/720p-5s.mp4 -->

The index (`moov`) comes before the media (`mdat`). A player can start and seek after fetching
the first bytes.

<!-- file: mp4/non-faststart-720p-5s.mp4 -->

The same resolution, duration and codecs, with `moov` at the end. A progressive player has to
reach the end of the file before it can play. A range request does that quickly. A server
without range support turns it into a full download.

## How do I test seeking and range requests?

<!-- file: mp4/50mb.mp4 -->

Two minutes of 720p. It is large enough that a seek which downloads from the start shows
plainly in the network panel.

<!-- file: mp3/sine-440hz-30s.mp3 -->

Thirty seconds of MP3 with a Xing header. The header lets a seek by time land where it should.
Without it, the player estimates from the file size and lands somewhere else.

<!-- file: bin/incrementing-1mb.bin -->

Bytes 00 to FF, repeating, with no decoder in the way. The first byte of a range response is
the requested offset modulo 256. So an off-by-one range shows at once.

## Which codecs and tracks break players?

<!-- file: mp4/h264-baseline-720p-5s.mp4 -->

H.264 in the constrained profile that older devices and some hardware decoders need. We read the
profile and level above from the stream, not from the encoder settings.

<!-- file: webm/720p-5s-vp9.webm -->

VP9 video with Opus audio in WebM, the royalty-free pair. Use it to see what a player does when
it is handed something other than H.264.

<!-- file: mp4/no-audio-720p-5s.mp4 -->

No audio track at all. Code that builds an audio graph or shows a volume control without
checking fails here, or shows a control that does nothing.

<!-- file: mp4/vertical-1080x1920-5s.mp4 -->

Portrait video. Players and thumbnailers that assume landscape crop it or shrink it into a
strip.

<!-- file: wav/sine-440hz-3s-48k-24bit-stereo.wav -->

24-bit audio behind a 68-byte header. A player that skips a fixed 44 bytes plays the end of the
header as audio.

<!-- file: opus/30s.opus -->

Opus decodes at 48 kHz, whatever rate the source had. A player or analyser that expects the
original rate back gets the duration or the pitch wrong.

## How do I test adaptive streaming?

<!-- file: hls/multi-bitrate/master.m3u8 -->

Two renditions, 360p and 720p. Each has a BANDWIDTH measured from its segments. Throttle the
connection and an adaptive player should step down to 360p. It should step back up when the
connection recovers.

The same files sit with the rest of their formats on [MP4](/mp4), [WebM](/webm), [HLS](/hls)
and [WAV](/wav).
