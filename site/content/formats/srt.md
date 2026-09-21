SubRip is the subtitle format every player reads, and the one with the most unforgiving
layout: numbered cues, comma-separated milliseconds, and CRLF line endings, separated by blank
lines. A stray blank line or a missing cue number breaks parsers that were written against a
single well-formed example.

`srt/3-cues.srt` is three consecutive cues of three seconds each — the smallest useful
subtitle file, small enough to read in full while you work out what a parser did with it.

The line endings matter more than they look. SubRip files are written with CRLF, and code that
normalises to LF on read and writes the file back out has quietly changed the format; the
fixture is published with CRLF so that round trip is testable.

Use it to test subtitle parsing, conversion to WebVTT, player upload forms and media
pipelines. Related formats: [WebVTT](/vtt), which browsers read natively, and
[text files](/txt).
