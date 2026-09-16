One script, and deliberately only one. `js/hello-console.js` defines a function and logs a
line — that is the entire file, so what it can do is obvious at a glance.

The restraint is the point. Nothing in this catalog reaches the network, touches the DOM or
evaluates a string, and a validator checks that on every build: no `eval`, no `Function`
constructor, no `fetch`, no `XMLHttpRequest`. A JavaScript fixture that could do anything
interesting would be a liability for anyone who serves it, and a file that gets flagged by a
scanner is no use as a test file.

That makes it suitable for the cases where you need a real script rather than a plausible one:
checking that an upload form accepts `.js`, that a bundler or minifier reads it, that a
content-type is served correctly, or that a sandboxing policy behaves the way you expect when
a script is actually present.

It is served as `text/javascript` with UTF-8. Related formats: [HTML](/html) and
[CSS](/css).
