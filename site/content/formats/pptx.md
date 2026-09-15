PPTX is PowerPoint's format, a ZIP archive of XML parts like DOCX and XLSX. These
presentations use widescreen 16:9 title-and-content slides of Lorem Ipsum, the default shape
of a new deck.

`pptx/1slide.pptx` is a single slide, the smallest useful presentation for upload forms and
thumbnailers. `pptx/10slides.pptx` has ten slides, each with its own title, which is enough
to test slide counting, navigation, per-slide text extraction and conversion to PDF or
images.

`pptx/1mb.pptx` reaches about 1 MB with one slide per embedded incompressible noise image,
each with a speaker note, so its size is honest and its notes give extraction tools something
to find. None of the files contains macros; a .pptx cannot carry them.

Use them to test document converters, preview generators, search indexers and upload forms
that accept presentations. Related formats: [DOCX](/docx) and [PDF](/pdf).
