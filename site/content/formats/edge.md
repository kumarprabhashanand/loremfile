Most test files are meant to be read successfully. These are not. Every file under `edge/`
is wrong on purpose, in one declared way: empty, cut short, malformed, or carrying bytes
that do not match the name and content type it is served with.

Each is served as the type its extension claims, because that is the situation worth
testing. `edge/png-with-pdf-extension.pdf` arrives as `application/pdf` and is a PNG;
`edge/pdf-truncated-60pct.pdf` reads as a PDF until it stops mid-object. Sniffing the type
from the extension, or assuming a parser raises a tidy error, are mistakes these files find.

Each also says what is wrong with it: every row below carries a `damage` sentence, the
valid file to `compare_with`, and an `outcome` — `must-fail` when every conforming reader
must refuse it, `may-recover` when part of it still reads, `varies` when readers disagree.
Only `must-fail` means a reader that copes is wrong.

Two are valid twice over: `edge/pdf-zip-polyglot.pdf` is a PDF *and* a zip archive,
`edge/gif-zip-polyglot.gif` a GIF and a zip. Nothing in the bytes decides which, which is
what makes them worth feeding to type detection. That shape is also how malware travels, so
scanners and corporate proxies sometimes refuse a polyglot or strip the archive in transit:
if a download arrives short, check [sha256sums.txt](/sha256sums.txt) first.

Use them on upload forms, import pipelines, thumbnailers and archive extractors —
`edge/zip-directory-traversal-name.zip` holds an entry named `../evil.txt` and tells you
whether yours writes outside the directory it was given. Related: [PDF](/pdf), [ZIP](/zip).
