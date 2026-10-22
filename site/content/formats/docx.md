This is a Lorem Ipsum DOCX file: a Word document with a heading and placeholder paragraphs in
Word's default styles.

<!-- file: docx/1page.docx -->

`docx/with-tracked-changes.docx` holds one deletion of "cancelled", one insertion of
"confirmed" and one comment: an extractor that reads the XML naively returns the deleted word
as current text, and only accepting the changes leaves "confirmed".

`docx/anchored-image-with-alt-text.docx` floats its 1 image in an anchor with alt text, where
`docx/with-images.docx` places its 2 inline: a converter or accessibility checker that looks
only for inline pictures misses the first. `docx/with-table.docx` holds a native table of 11
rows, header included, for extractors that flatten tables into text or drop them.

`docx/1page.docx` stores no page count of its own, so "one page" is what Word renders, and a
page-count check on a .docx needs a renderer. `docx/1mb.docx` and `docx/10mb.docx` reach
1,024,867 and 10,110,885 bytes with 5 and 51 embedded images, for upload limits that should be
hit by a real document.
