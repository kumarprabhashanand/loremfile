Binary files are raw bytes with no format at all, which makes them the right tool for testing
everything around a file rather than inside it: upload limits, range requests, checksums,
progress bars and storage quotas.

Sizes come in both units. `bin/1mb.bin` is exactly 1,000,000 bytes and `bin/1mib.bin` is
exactly 1,048,576, and there are boundary siblings one byte either side, such as
`bin/10mib-plus-1.bin`, for testing the edge of a limit instead of its middle. The sized
files are high-entropy SHAKE-256 output, so they do not compress and a transfer's size is
honest.

Patterned files cover the opposite cases: `bin/zeros-1mb.bin` compresses to almost nothing,
`bin/ones-1mb.bin` is all 0xFF bytes, and `bin/incrementing-1mb.bin` repeats 0x00 to 0xFF, so
any byte offset is visible by eye, which helps when checking a range response. The smallest
file, `bin/1-byte.bin`, is a single NUL byte. For readable filler of exact sizes, see
[text files](/txt).
