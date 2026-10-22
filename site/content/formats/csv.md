`csv/people-10-utf8-bom.csv` starts with a UTF-8 byte-order mark, which a reader that does not
strip it attaches to the first column name. `csv/people-10-semicolon.csv` uses `;` as its
delimiter, as European locales export, where `csv/people-10.csv` uses `,`.

`csv/people-10-crlf.csv` ends every record in CR LF, so a reader that splits on LF alone leaves
a carriage return on the last column. `csv/people-10-quoted-newlines.csv` has a newline inside
a quoted field, so its 10 rows take 20 lines and a reader that splits on lines gets the row
count wrong. `csv/people-10-quoted-commas.csv` has a comma inside a quoted field, which breaks
splitting on commas.

`csv/people-1000.csv` and `csv/people-100k.csv` hold 1,000 and 100,000 rows of the same 14
columns in 249,645 and 25,395,296 bytes. `csv/1mb.csv` and `csv/10mb.csv` are 965,447 and
9,749,583 bytes, prefixes of the same rows, for upload limits.
