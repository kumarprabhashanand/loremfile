A parser test has two halves: files that must load, and load correctly, and files that must
not load or must fail cleanly. The valid files below carry props in their manifest entries
that say what a correct read finds. The broken ones carry an `outcome`, shown beside each
link: `must-fail`, `may-recover` or `varies`.

## Proving a file loaded correctly

<!-- file: pdf/a4-3pages.pdf -->

Its manifest entry lists `contains_text`, strings taken from the text it was generated from.
Assert that each one appears in what your extractor returns, after collapsing whitespace,
and the test proves the pages were read rather than that the call returned.

<!-- file: docx/with-tracked-changes.docx -->

One deletion, one insertion and one comment. Joining all the XML text returns the deleted
word as if it were current; the entry's props record the deleted, inserted and current text
to compare with.

<!-- file: pdf/scanned-1page.pdf -->

A page that looks readable and has no text layer, so extraction returns an empty string. A
pipeline should notice and send it to OCR rather than store an empty document.

<!-- file: json/all-types.json -->

Integers beyond 2^53 and 2^63, negative zero and a surrogate pair: the values that change on
a round trip through a double or a careless string decoder.

## Text that splits in the wrong place

<!-- file: csv/people-10-quoted-newlines.csv -->

A quoted field holding a real newline. Splitting the file into lines before parsing it as
CSV cuts that record in two.

<!-- file: csv/people-10-utf8-bom.csv -->

A UTF-8 byte-order mark, which many readers leave attached to the first column name, so a
lookup by that name fails.

<!-- file: txt/utf16be-no-bom.txt -->

UTF-16 big-endian with no byte-order mark for a detector to find. Code that decides the
encoding from a BOM reads it as the wrong one.

## Files that must fail

<!-- file: edge/json-trailing-comma.json -->

Commas before closing brackets: valid JavaScript, invalid JSON. A conforming JSON parser
refuses it, so a reader that accepts it is not parsing JSON.

<!-- file: edge/xml-unclosed-tag.xml -->

An element that is never closed. XML 1.0 requires a parser to stop rather than guess where
the element ends.

<!-- file: edge/zero-byte.json -->

No bytes at all, where JSON requires a value. Check that the error says the file is empty,
not something about an unexpected end of input.

## Files that may be recovered

<!-- file: edge/zip-truncated-50pct.zip -->

The first half of a zip: the local headers survive and the central directory does not. A
reader that walks local headers recovers the surviving entries; one that starts from the
central directory finds nothing.

<!-- file: edge/pdf-truncated-60pct.pdf -->

The first part of a PDF, cut before its cross-reference table and trailer. Readers that
rebuild the table by scanning the file recover the pages that survive.

<!-- file: edge/utf8-invalid-bytes.txt -->

Text served as UTF-8 with byte sequences UTF-8 does not allow. Strict decoding fails, and
replacing the bad bytes recovers the rest. Either is right; silently dropping lines is not.

## Files readers disagree on

<!-- file: edge/json-bom.json -->

Valid JSON behind a byte-order mark that RFC 8259 does not allow. Some parsers skip the mark
and some refuse the file, so pin down which behaviour your code relies on.

<!-- file: edge/csv-ragged-rows.csv -->

Rows with fewer and more fields than the header. RFC 4180 says rows should match, not what a
reader does when they do not: pad, trim or refuse, and test that your code does the one you
chose.

## Limits

<!-- file: json/nested-100-levels.json -->

An object nested 100 levels deep. A recursive parser with a lower depth limit should refuse
it with an error rather than crash.

<!-- file: txt/very-long-line-1mb.txt -->

A single line filling the whole file, for line-based readers that hold a line in a fixed
buffer.

Every broken file, with the exact damage and the valid file to compare it with, is on the
[edge cases page](/edge).
