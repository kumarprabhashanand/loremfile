WebVTT is the subtitle format browsers read natively through a `track` element, and it differs
from SubRip in ways that matter to a parser: a `WEBVTT` signature on the first line, dotted
rather than comma-separated milliseconds, and optional blocks that simpler readers have to
skip rather than choke on.

`vtt/3-cues.vtt` is the signature and three plain cues — what a `track` element needs and
nothing more. It is small enough to read in full, which makes it a good first case when
something in a player is not displaying subtitles at all.

Because the difference from SubRip is mostly punctuation, the two formats are easy to convert
between and easy to convert wrongly. Publishing both lets you test a conversion in either
direction against a reference file rather than against your own output.

Use it to test browser subtitle rendering, conversion tooling, and upload forms for media
platforms. Related formats: [SRT](/srt) and [HTML](/html).
