A HAR file is the JSON a browser's network panel exports: a log of requests, responses,
timings and headers. Tools that read them include performance dashboards, test harnesses and
support pipelines where a user is asked to attach a network trace.

`har/simple-3-requests.har` describes one page and three requests — a document, a stylesheet
and an image — with fixed start times and timings. Because every timestamp is pinned, the file
is the same on every build rather than a record of when it happened to be generated, so it can
be committed as a test fixture and compared byte for byte.

It is valid JSON, so it doubles as a test of nested-structure handling: a HAR is considerably
deeper than the flat objects most JSON fixtures provide, and it is served as
`application/json`, which is worth checking against tools that expect a `.har` extension to
mean something else.

Related formats: [JSON](/json) and the [web app manifest](/webmanifest).
