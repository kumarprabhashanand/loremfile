Plain text is rarely as plain as it looks. These files cover exact sizes, both common line
endings, and the character encodings a parser is likely to meet.

Sizes: `txt/lorem-1kb.txt`, `txt/lorem-100kb.txt`, `txt/lorem-1mb.txt` and
`txt/lorem-10mb.txt` are exact decimal sizes of Lorem Ipsum, and `txt/lorem-1mib.txt` and
`txt/lorem-10mib.txt` exact binary ones. `txt/very-long-line-1mb.txt` is a single line of
1,000,000 bytes, for tools that read a whole line into memory.

Line endings: `txt/lf.txt` and `txt/crlf.txt` are 100 lines each, with Unix and Windows
endings.

Encodings: `txt/utf8-bom.txt` and `txt/utf16le-bom.txt` start with byte-order marks, while
`txt/latin1.txt`, `txt/windows-1252.txt` and `txt/shift-jis.txt` are not UTF-8 at all.
`txt/utf8-multilingual.txt` has a line per script plus emoji, combining marks, bidi controls
and unusual spaces, and `txt/emoji-only.txt` contains nothing but emoji sequences.

`txt/utf16be-no-bom.txt` encodes ASCII Lorem Ipsum as UTF-16 big-endian without a BOM.
Unlike `txt/utf16le-bom.txt`, it gives an encoding detector no byte-order marker. The
declared charset is `utf-16be`; the validator independently measures the byte order from
the NUL lane in these ASCII code units and rejects little-endian bytes or an added BOM.

Related formats: [Markdown](/md), [log files](/log), [INI](/ini) and [binary files](/bin).
