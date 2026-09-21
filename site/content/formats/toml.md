TOML is a configuration format designed to be unambiguous, used by Cargo, Python's
pyproject files and many other tools. `toml/config.toml` covers the parts of the
specification that simple parsers skip.

It has tables, nested tables and an array of tables; multi-line basic strings and literal
strings; integers with underscores; and all four kinds of date and time value TOML defines:
offset date-times, local date-times, dates and times. Date-times are where implementations
differ most, for example by converting a local date-time to UTC or refusing a bare time.

Use it to test configuration loaders, TOML-to-JSON converters, and editors that validate or
highlight TOML. Parse it, serialise the result back and compare the two: a round trip that
changes a value or its type points at a gap in the parser. Related formats: [YAML](/yaml),
[JSON](/json) and [INI](/ini).
