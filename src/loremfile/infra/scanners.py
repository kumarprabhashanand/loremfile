"""The scanner paths the `loremfile_scanner_paths` custom rule blocks (docs/08 §5.7).

One list, three readers: the committed rule's expression, which a test generates from it;
the probe, which requests these paths after an apply; and `usage`, which counts the requests
for them in the zone's analytics. A path added here and not to the rule, or the other way
round, fails the test rather than leaving the measurement counting something the rule does
not block.

Exact paths match with `eq`, prefixes with `starts_with()`, both case-sensitive, as every
rules-language string operator is. Nothing here may match `/.well-known/`, where
security.txt, the API catalog and the agent skills live.
"""

from __future__ import annotations

from typing import Any, Final

RULE_REF: Final = "loremfile_scanner_paths"
#: Matched whole.
EXACT: Final = ("/wp-login.php", "/xmlrpc.php", "/.env")
#: Matched as prefixes; each ends in `/`, so `/wp-admin` and `/.github/` stay out.
PREFIXES: Final = ("/wp-admin/", "/.git/")
#: Never matched. The probe asserts it is not refused.
NEVER: Final = "/.well-known/"

PATH = "http.request.uri.path"


def expression() -> str:
    """The rule's expression, as committed in `infra/rulesets/http_request_firewall_custom.json`."""
    terms = [f'starts_with({PATH}, "{prefix}")' for prefix in PREFIXES]
    terms += [f'{PATH} eq "{path}"' for path in EXACT]
    return f"({' or '.join(terms)})"


def matches(path: str) -> bool:
    """What the rule does to a request path, in Python, for tests and the probe."""
    return path in EXACT or path.startswith(PREFIXES)


def analytics_filter() -> list[dict[str, Any]]:
    """The same paths as a GraphQL `OR` over `clientRequestPath`.

    `like` takes `%` as its wildcard; no path here carries a `%` or `_`, so each prefix
    pattern means exactly that prefix (`test_scanner_rule.py` keeps it so).
    """
    return [{"clientRequestPath": path} for path in EXACT] + [
        {"clientRequestPath_like": f"{prefix}%"} for prefix in PREFIXES
    ]
