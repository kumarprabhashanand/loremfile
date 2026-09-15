XML parsers differ most on namespaces, and XML feeds are still everywhere. These three files
cover plain records, namespaces and a real feed.

`xml/people-10.xml` holds ten records of the shared people dataset as elements, one child
element per column: the simplest shape for testing a mapping from XML to rows.

`xml/with-namespaces.xml` has a default namespace, two prefixed namespaces, a namespaced
attribute and `xml:lang`. Code that matches element names without their namespace, or ignores
the default namespace, finds nothing or the wrong thing, which is the most common bug in
hand-written XML handling.

`xml/rss2-feed.xml` is an RSS 2.0 feed with ten items and fixed publication dates, for feed
readers, podcast tools and aggregators. Like all markup on this site, the files are served
with a sandbox Content-Security-Policy, so opening one in a browser runs nothing.

Related formats: [JSON](/json) and [YAML](/yaml).
