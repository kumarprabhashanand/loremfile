You are testing a parser, and that is two jobs. Some files must load, and load correctly.
Others must fail, or fail cleanly.

The valid files below carry props in their manifest entries. The props say what a correct read
finds. The broken files carry an `outcome`, shown beside each link: `must-fail`, `may-recover`
or `varies`.

## How do I prove a file loaded correctly?

<!-- file: pdf/a4-3pages.pdf -->

Its manifest entry lists `contains_text`: strings taken from the text we generated the file
from. Assert that each one appears in what your extractor returns, after you collapse
whitespace. If they do, the pages were read. A call that merely returned proves nothing.

<!-- file: docx/with-tracked-changes.docx -->

One deletion, one insertion and one comment. Join all the XML text and you get the deleted word
as if it were current. The entry's props record the deleted, inserted and current text, so you
can compare.

<!-- file: pdf/scanned-1page.pdf -->

A page that looks readable and has no text layer, so extraction returns an empty string. A
pipeline should notice that and send the page to OCR. It should not store an empty document.

<!-- file: json/all-types.json -->

Integers beyond 2^53 and 2^63, negative zero and a surrogate pair. These are the values that
change on a round trip through a double or a careless string decoder.

## Where does text split in the wrong place?

<!-- file: csv/people-10-quoted-newlines.csv -->

A quoted field holding a real newline. Split the file into lines before you parse it as CSV,
and that record is cut in two.

<!-- file: csv/people-10-utf8-bom.csv -->

A UTF-8 byte-order mark. Many readers leave it attached to the first column name, so a lookup
by that name fails.

<!-- file: txt/utf16be-no-bom.txt -->

UTF-16 big-endian with no byte-order mark for a detector to find. Code that decides the
encoding from a BOM reads it as the wrong one.

## Files that must fail

<!-- file: edge/json-trailing-comma.json -->

Commas before closing brackets. That is valid JavaScript and invalid JSON. A conforming JSON
parser refuses it, so a reader that accepts it is not parsing JSON.

<!-- file: edge/xml-unclosed-tag.xml -->

An element that is never closed. XML 1.0 requires a parser to stop here. It must not guess where
the element ends.

<!-- file: edge/zero-byte.json -->

No bytes at all, where JSON requires a value. Check that the error says the file is empty. It
should not say something about an unexpected end of input.

## Files that may be recovered

<!-- file: edge/zip-truncated-50pct.zip -->

The first half of a zip. The local headers survive and the central directory does not. A reader
that walks local headers recovers the surviving entries. One that starts from the central
directory finds nothing.

<!-- file: edge/pdf-truncated-60pct.pdf -->

The first part of a PDF, cut before its cross-reference table and trailer. Readers that rebuild
the table by scanning the file recover the pages that survive.

<!-- file: edge/utf8-invalid-bytes.txt -->

Text served as UTF-8, with byte sequences that UTF-8 does not allow. Strict decoding fails.
Replacing the bad bytes recovers the rest. Either is right. Silently dropping lines is not.

## Files readers disagree on

<!-- file: edge/json-bom.json -->

Valid JSON behind a byte-order mark, which RFC 8259 does not allow. Some parsers skip the mark
and some refuse the file. Pin down which behaviour your code relies on.

<!-- file: edge/csv-ragged-rows.csv -->

Rows with fewer and more fields than the header. RFC 4180 says rows should match. It does not
say what a reader does when they do not. A reader can pad, trim or refuse. Pick one, and test
that your code does it.

## What happens at the limits?

<!-- file: json/nested-100-levels.json -->

An object nested 100 levels deep. A recursive parser with a lower depth limit should refuse it
with an error. It should not crash.

<!-- file: txt/very-long-line-1mb.txt -->

A single line that fills the whole file. It is for line-based readers that hold a line in a
fixed buffer.

Every broken file, with the exact damage and the valid file to compare it with, is on the
[edge cases page](/edge).
