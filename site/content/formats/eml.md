An `.eml` file is a single email message saved the way a mail client writes it: headers, a
blank line, then the body, with MIME parts if there are attachments. Mail parsers have to cope
with all of it, and these files exercise the common shapes.

`eml/plain-text.eml` is the simplest thing a parser has to read — one `text/plain` part with a
fixed date and Message-ID. `eml/with-attachments.eml` carries two published fixtures as
attachments, a PDF and a PNG, read from the bytes that were actually published, so the parts
you extract match files you can fetch separately and compare against.

Nothing in these messages comes from the machine that built them. Dates, Message-IDs and MIME
boundaries are derived from a seed rather than the clock or the hostname, so the files are
identical on every build and contain no personal data.

Use them to test mail parsers, importers, attachment extraction and preview rendering. Related
formats: [mbox](/mbox) for several messages in one file, and [text files](/txt).
