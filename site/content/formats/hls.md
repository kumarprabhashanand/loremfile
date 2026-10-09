This is a sample HLS stream you can play straight from its URL: a VOD playlist and the
segments it lists.

<!-- file: hls/720p-10s/index.m3u8 -->

HLS, Apple's HTTP Live Streaming, delivers video as a playlist of short segments that a player
fetches one by one, so it cannot be tested with a single file. `hls/720p-10s/index.m3u8` uses
relative segment URIs and closes with an `#EXT-X-ENDLIST` tag. The segments sit beside it,
from `hls/720p-10s/seg-000.ts` to `hls/720p-10s/seg-004.ts`, each carrying H.264 video and
AAC audio in an MPEG-2 transport stream. Because the URIs are relative, the stream works from
any host that serves the same layout, including a local mirror.

Point a player such as hls.js, Safari or ExoPlayer at the playlist URL to test playback,
seeking and segment fetching. Every segment is served with open CORS, so a player on another
origin can load it. Related formats: [TS](/ts) and [MP4](/mp4).
