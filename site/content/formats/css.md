Stylesheets are parsed by more things than browsers: build tools, minifiers, linters, editors
and anything that rewrites asset URLs. These files give those tools something real to read
without pulling in a framework.

`css/basic.css` is a small stylesheet that uses the features a modern parser has to
understand: custom properties, a grid layout, a media query for dark mode, and a feature
query. It is short enough to read in full, so when a tool mangles it you can see exactly what
changed.

Nothing here reaches the network. There is no `@import`, no web font and no background image
pointing at another host, which means the file behaves identically offline and cannot quietly
become a request you did not expect. A validator checks that on every build.

Use it to test CSS parsers, bundlers, style sanitisers and upload forms that accept `.css`.
It is served as `text/css` with UTF-8. Related formats: [HTML](/html) and
[JavaScript](/js).
