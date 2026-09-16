INI files have no single specification, which is exactly why parsers disagree about them.
`ini/config.ini` covers the differences that trip them: sections, comments starting with both
`;` and `#`, quoted values, empty values, a comma-separated list, and non-ASCII characters.

Each of those is a choice a parser makes silently. Some treat `#` as a comment only at the
start of a line; some keep the quotes as part of the value; some drop keys whose value is
empty; some read the file as ASCII and mangle anything else. Loading this file and printing
what your parser saw is the fastest way to learn which choices it made.

Use it to test configuration loaders such as Python's `configparser`, application settings
screens, and tools that convert INI to JSON or YAML. It is served as plain text, UTF-8 with
LF line endings. Related formats: [TOML](/toml) and [YAML](/yaml), and [text files](/txt)
for encodings.
