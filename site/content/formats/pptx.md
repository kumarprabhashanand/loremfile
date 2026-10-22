`pptx/with-hidden-slide.pptx` has 3 slides, 1 of them marked hidden. A slideshow skips it,
but a renderer or PDF converter that draws every slide of `pptx/with-hidden-slide.pptx` shows
it, and a counter that ignores the flag reports all 3: the one failure here that looks like
success.

`pptx/with-table.pptx` holds a native table and `pptx/with-chart.pptx` a native chart, each on
its own slide: an extractor that reads only text frames finds none of the table's text in
the first, and a converter that cannot draw charts leaves a hole in the second, whose numbers
live in the workbook PowerPoint embeds beside it.

`pptx/aspect-4-3-5slides.pptx` measures 9,144,000 by 6,858,000 EMU, 4:3, where `pptx/1slide.pptx`
measures 12,191,695 by 6,858,000, widescreen: a thumbnailer or converter that assumes widescreen
crops or letterboxes it. `pptx/1mb.pptx` has speaker notes on all 5 of its slides and 5
embedded images, for extraction tools that must find notes. `pptx/10slides.pptx` has 10
titled slides for slide counting and per-slide text, and `pptx/1slide.pptx` is the smallest,
for upload forms and thumbnailers.
