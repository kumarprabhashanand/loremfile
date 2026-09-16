EPUB is the open e-book format: a ZIP container holding XHTML content, a package document
that lists it, and a navigation document for the table of contents. Many files that call
themselves EPUB are renamed ZIP archives that some readers tolerate and validators reject.

`epub/epub3-3chapters.epub` is a real EPUB 3.0 book: three XHTML chapters of Lorem Ipsum, a
navigation document with a table of contents, and a stylesheet. The `mimetype` entry comes
first and is stored uncompressed, as the container specification requires, so tools that
sniff the first bytes recognise the file. The identifier and modification date are fixed, so
the bytes do not move between builds.

Use it to test e-reader apps, format sniffers, EPUB validators, converters to PDF or HTML,
and upload forms that accept books. Related formats: [PDF](/pdf), [DOCX](/docx) and
[text files](/txt).
