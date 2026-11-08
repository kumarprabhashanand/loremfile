`eml/plain-text.eml` is the message every parser must read: one `text/plain` part, declared
UTF-8 and quoted-printable, with every line ending in CR LF, so a parser that splits on `\n`
alone leaves a stray `\r` on each line, and one that skips quoted-printable decoding shows an
`=` wherever a line was wrapped.

`eml/with-attachments.eml` is `multipart/mixed` with a text part and two attachments, a PDF and
a PNG, each base64-encoded, so a parser that takes the message for one body finds only the text,
and one that skips base64 writes files that nothing opens. The attachments are the bytes of
`pdf/minimal.pdf`, 586 bytes, and `png/100x100.png`, 1,387 bytes, which are published too, so an
extractor can be checked by comparing what it writes with those two fixtures.
