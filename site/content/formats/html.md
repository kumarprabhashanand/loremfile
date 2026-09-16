HTML is read by far more than browsers: sanitisers, converters, scrapers, email clients and
anything that generates a preview. These documents give each of those something valid and
predictable to work with.

`html/basic.html` is a minimal, valid HTML5 document — a doctype, a declared charset, a
heading and two paragraphs. `html/all-elements.html` is the broad one: semantic sections, a
table with a caption and header cells, a form with no action, lists, a figure and media
elements. `html/with-inline-css.html` moves the styling into a style block, and
`html/with-inline-js.html` carries a single inline script that logs one line and does nothing
else.

That last file is the only script in the catalog, and it is deliberate: there are no event
handler attributes, no `javascript:` URLs and no references to other hosts anywhere, and a
validator enforces that on every build. The edge serves it under a sandboxing policy.

Use them to test parsers, sanitisers, converters and upload handling. Related formats:
[CSS](/css), [JavaScript](/js) and [Markdown](/md).
