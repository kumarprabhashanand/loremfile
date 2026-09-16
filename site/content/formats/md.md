Markdown is plain text with lightweight formatting, and every renderer treats its corners a
little differently. `md/readme-style.md` is a README-shaped Markdown document of exactly
4,096 bytes, the kind of file every source repository has at its root.

The exact size is useful on its own. 4,096 bytes is a common buffer and memory page size, so
the file lands exactly on a boundary that exposes off-by-one mistakes in code that reads text
in fixed chunks. Its content makes it a realistic input for renderers, syntax highlighters
and documentation tools.

Use it to test Markdown rendering in editors and previews, static site generators, search
indexers, and upload forms that accept `.md` files. It is UTF-8 with LF line endings and is
served as `text/markdown`, so it also checks how a client handles that MIME type when it does
not recognise it. Related formats: [text files](/txt).
