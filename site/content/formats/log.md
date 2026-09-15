Log files are text, but tooling meets them in two distinct shapes, and both are here.

`log/nginx-access-1000-lines.log` is 1,000 lines in the nginx combined access-log format:
client address, timestamp, request line, status, bytes, referrer and user agent. The
timestamps are fixed and every client address is an RFC 5737 documentation address, so the
file contains no real IP addresses and parses the same way every time.

`log/json-lines-app-1000.log` is 1,000 application log records with one JSON object per line,
the structured shape that log shippers and observability pipelines prefer.

Use them to test log parsers and shippers, dashboards that must handle both shapes, grok and
regex patterns, and upload forms for diagnostic files. Both are UTF-8 with LF line endings.
Related formats: [NDJSON](/ndjson), which has the same one-object-per-line structure, and
[text files](/txt).
