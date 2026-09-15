DOCX is Microsoft Word's format: a ZIP archive of XML parts. These documents were written by
python-docx and then normalised, so their bytes never change between builds and the hash in
the manifest stays true.

`docx/1page.docx` is a heading and three paragraphs of Lorem Ipsum in Word's default styles.
Its page count is what Word renders, because a .docx stores no page count of its own.
`docx/with-images.docx` embeds two published PNG fixtures as pictures, and
`docx/with-table.docx` holds a ten-row table of the shared people dataset with a bold header
row.

For size limits, `docx/1mb.docx` and `docx/10mb.docx` reach their size with embedded
incompressible noise images rather than padding, so a compressing upload path cannot shrink
them. None of the files contains macros; a .docx cannot carry them.

Use them to test document upload forms, text extraction, converters and previewers. Related
formats: [PDF](/pdf), [RTF](/rtf) and [XLSX](/xlsx).
