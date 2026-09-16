An mbox holds several messages in one file, each introduced by a `From ` separator line at the
start of a line. It is the format mail archives and account exports still use, and the one
where parsers most often go wrong — because a body line that happens to begin with `From `
looks exactly like a separator unless the reader is careful.

`mbox/3-messages.mbox` contains three plain-text messages separated by `From ` lines, each
with a fixed date and Message-ID. It is small enough to read in a text editor, so when a
parser splits it into two messages or four you can see immediately where it went wrong.

Nothing comes from the machine that built it: dates and Message-IDs are derived from a seed
rather than the clock, so the file is identical on every build and holds no personal data.

Use it to test mail importers, archive migration, search indexing and anything that has to
iterate messages in a single file. Related format: [EML](/eml) for single messages.
