`pdf/scanned-1page.pdf` is one page of image with 0 characters of text, so extraction returns
an empty string and a pipeline that expects text from every PDF needs OCR for it.
`pdf/form-fields-1page.pdf` has 6 form fields, 3 of them filled, for form extraction and
filling. `pdf/a4-encrypted-1page.pdf` is encrypted, PDF 1.5, and opens with the password
loremfile, published so the test can pass.

`pdf/a4-landscape-1page.pdf` measures 841.89 by 595.28 points and `pdf/letter-1page.pdf` 612 by
792: a renderer that assumes A4 portrait crops both. `pdf/blank-1page.pdf` is a valid page with
nothing on it, and `pdf/minimal.pdf` is the smallest valid PDF here at 586 bytes, for parsers
that must not crash on the minimum.

`pdf/a4-with-table-1page.pdf` holds a table and `pdf/a4-with-images-2pages.pdf` 2 pages that
embed images, for extractors that must keep structure and pull pictures out.
`pdf/a4-1page.pdf`, `pdf/a4-3pages.pdf` and `pdf/a4-10pages.pdf` are 1, 3 and 10 pages of text,
for page counting. `pdf/1mb.pdf` and `pdf/10mb.pdf` are 976,137 and 9,924,917 bytes over 4 and
42 pages, for upload limits.
