A web app manifest is the JSON a browser reads to learn a site's name, icons, colours and
display mode — the file that decides what an installed web app looks like on a home screen.

`webmanifest/site.webmanifest` carries a name, short name, start URL, scope, display mode,
theme and background colours, and two icons. The icons point at published PNG fixtures, so a
tool that follows them gets real images back rather than a 404, which is the difference
between testing a manifest parser and testing it properly.

It is served as `application/manifest+json`, a content type plenty of pipelines have never
seen. That alone is worth checking: servers that guess types from extensions often return
`application/octet-stream` for `.webmanifest`, and browsers then ignore the file entirely
without an obvious error.

Use it to test manifest parsing, install prompts, icon resolution and content-type handling.
Related formats: [JSON](/json) and [HTML](/html).
