## How is a name put together?

A URL is `https://loremfile.dev/{format}/{name}`. The format matches `^[a-z0-9]+$`. The name is
lowercase kebab-case followed by one or more extensions: `^[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+)+$`.
There are no capitals, spaces or underscores.

A name is a list of tokens separated by hyphens: a variant, then a dimension, duration, count
or size, then qualifiers. They always come in that order.

Three examples show it:

- `jpg/progressive-1920x1080.jpg` is a variant and a dimension.
- `mp4/no-audio-720p-5s.mp4` is a variant, a dimension and a duration.
- `csv/people-10-utf8-bom.csv` is a dataset, a count and an encoding qualifier.

## What is the difference between kb and kib?

Size tokens say which unit they mean. `kb`, `mb` and `gb` are decimal, so `bin/1mb.bin` is
exactly 1,000,000 bytes. `kib`, `mib` and `gib` are binary, so `bin/1mib.bin` is exactly
1,048,576 bytes.

Upload limits are written both ways in the wild. A limit tested with the wrong unit passes
files it should refuse.

Boundary files sit one byte either side of a limit. `bin/10mib-plus-1.bin` is 10,485,761 bytes,
and `bin/1mb-minus-1.bin` is 999,999 bytes. Test the edge of a limit, not its middle.

## How exact is a size?

The manifest's `size_class` says:

- `exact`: the byte count is the number in the name.
- `boundary`: the byte count is exactly one byte above or below that number, as the plus-1 and
  minus-1 files are.
- `approx`: the file was fitted to within 5% of that number, as `csv/1mb.csv` is, because a CSV
  cannot end halfway through a row.
- `free`: the name describes the content, and the size follows from it.

## How is HLS named?

HLS is the one nested case. A playlist sits at `hls/{variant}/index.m3u8`, and its numbered
segments sit beside it, such as `hls/720p-10s/seg-000.ts`.

## Is there a name I can guess?

`/{format}/sample.{format}`, for example `/pdf/sample.pdf`, serves the same bytes as the file that
format's page starts with, for every format except `hls`, `edge`, `ogv`, `ts` and `opus`; `sample` is
reserved for it.

## Will a name ever point at different bytes?

No. The bytes at a published name never change. A fix gets a new name, and the old entry points
to its replacement.

In rare cases a file can be withdrawn. See the [terms of use](/legal/terms).
