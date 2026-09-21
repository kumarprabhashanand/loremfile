YAML is the configuration language of CI systems, Kubernetes and countless tools, with a large
specification whose features parsers implement differently or not at all.
`yaml/config-all-types.yaml` gathers the ones that trip them.

It uses anchors and aliases to reuse values, and a merge key to combine mappings; it contains
two documents in one stream; it has literal and folded block scalars, which differ in how they
keep line breaks; and it includes every scalar type, among them `.inf`, `.nan`, dates and
timestamps.

Each feature is a known source of disagreement. Some parsers reject merge keys, which YAML 1.2
no longer defines; some return only the first document; some turn dates into strings and
others into date objects. Load the file, print what your parser produced, and compare it with
what you expected.

Use it to test configuration loaders, linters and YAML-to-JSON converters. Related formats:
[JSON](/json), [TOML](/toml) and [INI](/ini).
