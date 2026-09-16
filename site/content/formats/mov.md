MOV is Apple's QuickTime container, MP4's older sibling, and what iPhones and many cameras
record. Both formats descend from the same file structure, so tools often accept one and
stumble over the details of the other.

`mov/720p-5s.mov` is 1280x720 at 30 frames per second, five seconds long, with H.264 video
and AAC audio. It is written with faststart, so the `moov` atom that indexes the media comes
before the media itself and playback can begin before the whole file has downloaded.

Use it to test upload forms that must accept phone videos, transcoders, thumbnailers, and
players that sniff the container rather than trusting the extension. The codecs match the
[MP4](/mp4) and [MKV](/mkv) fixtures, so a difference in behaviour points at the container.
The file is generated synthetically, with no real footage.
