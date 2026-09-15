Rich Text Format is the document format that survives everywhere: every word processor reads
it, and it is plain text with control words, so it can be inspected in any editor. That makes
it a useful control when a DOCX importer misbehaves.

`rtf/simple.rtf` was written by hand rather than by a library. It holds three paragraphs of
Lorem Ipsum in Times New Roman, with a font table and paragraph breaks, and every byte is
ASCII, so no reader has to guess an encoding.

Because it is so plain, the file isolates the basics: parsing the RTF header and font table,
turning control words into paragraphs, and extracting text. If a converter handles this file
and fails on a more complex document, the problem lies in the features that document adds,
not in RTF itself.

Use it for text extraction, document conversion and upload forms that accept RTF. Related
formats: [DOCX](/docx), [text files](/txt) and [PDF](/pdf).
