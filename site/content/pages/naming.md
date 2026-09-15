## The grammar

A URL is `https://loremfile.dev/{format}/{name}`. The format matches `^[a-z0-9]+$`. The name
is lowercase kebab-case followed by one or more extensions:
`^[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+)+$`. There are no capitals, spaces or underscores.

A name is a list of tokens separated by hyphens, in order: a variant, then a dimension,
duration, count or size, then qualifiers. `jpg/progressive-1920x1080.jpg` is a variant and a
dimension; `mp4/no-audio-720p-5s.mp4` adds a duration; `csv/people-10-utf8-bom.csv` is a
dataset, a count and an encoding qualifier.

## Sizes: kb is not kib

Size tokens are explicit about their units. `kb`, `mb` and `gb` are decimal, so
`bin/1mb.bin` is exactly 1,000,000 bytes. `kib`, `mib` and `gib` are binary, so
`bin/1mib.bin` is exactly 1,048,576 bytes. Upload limits are written both ways in the wild,
and a limit tested with the wrong unit passes files it should refuse.

Boundary files sit one byte either side of a limit: `bin/10mib-plus-1.bin` is 10,485,761
bytes and `bin/1mb-minus-1.bin` is 999,999 bytes. Test the edge of a limit, not its middle.

## How exact is a size?

The manifest's `size_class` says. `exact` means the byte count is the number in the name,
and `boundary` means it is exactly one byte above or below it, as the plus-1 and minus-1
files are.
`approx` means the file was fitted to within 5% of it, as `csv/1mb.csv` is, because a CSV
cannot end halfway through a row. `free` means the name describes the content and the size
simply follows from it.

## HLS

HLS is the one nested case: `hls/{variant}/index.m3u8` and its numbered segments beside it,
such as `hls/720p-10s/seg-000.ts`.

## Names never change

A published name keeps its bytes forever. A fix is a new name; the old entry stays and points
to its replacement.
