Most test files are meant to be read successfully. These are not. Every file under `edge/`
is wrong on purpose, in one declared way: empty, cut short, malformed, or carrying bytes
that do not match the name and content type it is served with.

Each file is served as the type its extension claims, because that is the situation worth
testing. `edge/png-with-pdf-extension.pdf` arrives as `application/pdf` and is a PNG;
`edge/pdf-truncated-60pct.pdf` reads as a PDF until it stops mid-object. Sniffing the
content type from the extension, trusting a `Content-Length`, or assuming a parser will
raise a tidy error are all mistakes these files find.

Every file here also says what is wrong with it. Its [manifest](/manifest.json) entry
carries one sentence of `damage`, the valid file of the same type to `compare_with`, and an
`outcome`: `must-fail` when every conforming reader has to refuse it, `may-recover` when
part of it can still be read, `varies` when readers disagree. Only `must-fail` means a
reader that copes is wrong.

Use them on upload forms, import pipelines, thumbnailers, virus and type scanners, and
anything that extracts an archive. `edge/zip-directory-traversal-name.zip` holds an entry
named `../evil.txt`: an extractor that joins entry names to a destination path without
sanitising them writes outside that directory, and this file tells you whether yours does.
The files are synthetic and harmless — no executable code, no real malware — so run them
only against systems you are authorised to test. Related formats: [PDF](/pdf),
[PNG](/png), [ZIP](/zip), [JSON](/json), [CSV](/csv).
