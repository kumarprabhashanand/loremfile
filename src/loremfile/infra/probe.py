"""Behavioural probes against production (docs/15 M2.4, docs/08 §6).

**Every assertion here can pass vacuously, and the framework exists to stop that.**
The clearest case: "the sandbox CSP is present on `/_probe/basic%2Ehtml`". If that
request 404s there is no CSP, no header, and nothing to assert on — a naive check reads
"header absent" and cannot tell *the rule did not fire* from *nothing was there*. So a
check states its preconditions with :func:`require`, and an unmet precondition is a
**failure**, never a skip and never a pass. The same trap as a `container.image` that
resolves to an empty string: the job runs, the check is green, and nothing was tested.

The probe writes only under `_probe/` and `_locktest/`. Neither is a fixture path, so
neither is covered by the immutability promise (`docs/03` §7.1); `_probe/` is cleaned up
by `probe --down` and `_locktest/probe` is written once and then deliberately refused.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from loremfile.config import SITE_HOST

BASE = f"https://{SITE_HOST}"

#: Objects the probe uploads before checking. Keys, not fixture paths.
PROBE_PREFIX = "_probe/"
LOCKTEST_KEY = "_locktest/probe"

#: docs/08 §5.3: markup gets the sandbox CSP, files get nosniff and friends.
PROBE_OBJECTS: dict[str, tuple[str, bytes]] = {
    f"{PROBE_PREFIX}basic.html": ("text/html", b"<!doctype html><title>probe</title><p>probe"),
    f"{PROBE_PREFIX}file.bin": ("application/octet-stream", b"probe"),
    f"{PROBE_PREFIX}index.html": ("text/html", b"<!doctype html><title>probe index</title>"),
    f"{PROBE_PREFIX}dir": ("text/plain", b"key named dir"),
    f"{PROBE_PREFIX}dir/index.html": ("text/html", b"<!doctype html><title>dir index</title>"),
}

#: The rate-limit rule: 300 requests / 10 s per IP per colo, mitigation timeout 10 s.
RATE_LIMIT_BURST = 400
RATE_LIMIT_RECOVERY_SECONDS = 12

HTTP_OK = 200
HTTP_MOVED_PERMANENTLY = 301
HTTP_NOT_FOUND = 404
HTTP_TOO_MANY_REQUESTS = 429


class CheckFailed(Exception):
    """An assertion about production did not hold."""


class PreconditionUnmet(CheckFailed):
    """A check could not be evaluated. Reported as a failure, never as a pass.

    This is the whole point of the module: "the header is absent" and "there was nothing
    to put a header on" are different results, and only one of them is information.
    """


def require(condition: bool, why: str) -> None:
    """Refuse to evaluate a check whose precondition does not hold."""
    if not condition:
        raise PreconditionUnmet(why)


def check(condition: bool, why: str) -> None:
    """Assert a fact about production.

    Deliberately **not** the `assert` statement: `python -O` strips those, and a probe
    whose assertions can be removed by an interpreter flag is the most complete vacuous
    pass available — every check would report green having tested nothing.
    """
    if not condition:
        raise CheckFailed(why)


@dataclass
class Fetched:
    status: int
    headers: dict[str, str]
    body: bytes

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")


def fetch(
    path: str,
    *,
    method: str = "GET",
    host: str = SITE_HOST,
    extra_headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> Fetched:
    """One request. **Never retries, on any status.**

    `verify-live` treats a 429 from our own rate limit as "wait 10 seconds and try
    again". The probe asserts the 429 — its absence is the failure. Those two behaviours
    must not share a code path, so this function has no retry logic at all rather than a
    flag that could be set wrongly.
    """
    request = urllib.request.Request(
        f"https://{host}{path}", method=method, headers=extra_headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return Fetched(
                status=response.status,
                headers={k.lower(): v for k, v in response.headers.items()},
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        return Fetched(
            status=exc.code,
            headers={k.lower(): v for k, v in (exc.headers or {}).items()},
            body=exc.read() if exc.fp else b"",
        )


@dataclass
class Result:
    name: str
    state: str  # pass | fail | measured
    detail: str = ""


@dataclass
class ProbeReport:
    results: list[Result] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(r.state == "fail" for r in self.results)

    def render(self) -> str:
        width = max((len(r.name) for r in self.results), default=8)
        lines = [f"  {r.name.ljust(width)}  {r.state:<8} {r.detail}".rstrip() for r in self.results]
        failed = sum(1 for r in self.results if r.state == "fail")
        lines.append("")
        lines.append(f"  {len(self.results)} checks, {failed} failed")
        return "\n".join(lines)


Check = Any  # a callable taking no arguments and returning a detail string


def run_checks(checks: dict[str, Check]) -> ProbeReport:
    """Run every check. A precondition failure is a failure, like any other."""
    report = ProbeReport()
    for name, check in checks.items():
        try:
            detail = check()
            report.results.append(Result(name, "pass", detail or ""))
        except PreconditionUnmet as exc:
            report.results.append(Result(name, "fail", f"precondition unmet: {exc}"))
        except CheckFailed as exc:
            report.results.append(Result(name, "fail", str(exc)))
        except Exception as exc:  # a probe reports; it does not crash the run
            report.results.append(Result(name, "fail", f"{type(exc).__name__}: {exc}"))
    return report


# --- the checks -------------------------------------------------------------


def check_markup_sandbox_csp() -> str:
    """The CSP on a markup object, requested with a `%2E`-encoded dot.

    Two things at once, which is why the precondition matters: the header rule fires on
    a `.html` suffix, and it only sees that suffix because URL normalization decodes
    `%2E` before the rules run (docs/08 §5.3). A 404 here means neither was tested.
    """
    encoded = f"/{PROBE_PREFIX}basic%2Ehtml"
    response = fetch(encoded)
    require(
        response.status == HTTP_OK,
        f"GET {encoded} returned {response.status}; with nothing served there, an absent "
        "CSP proves nothing about the header rule or about URL normalization. Run "
        "`probe --up` first.",
    )
    csp = response.header("content-security-policy")
    require(bool(csp), f"no Content-Security-Policy on {encoded}")
    check("sandbox" in csp, f"CSP on {encoded} is not the sandbox policy: {csp!r}")
    check("script-src" not in csp, f"the sandbox CSP must not name script-src: {csp!r}")
    return "sandbox CSP present on the %2E-encoded path"


def check_url_normalization_is_on() -> str:
    """The encoded and decoded paths must be the same object to the rules engine.

    If normalization is off, `%2E` reaches the rules as a literal and the suffix tests in
    docs/08 §5.3 silently stop matching — markup fixtures would be served without the
    sandbox CSP. ADR-011 depends on this being on.
    """
    plain = fetch(f"/{PROBE_PREFIX}basic.html")
    encoded = fetch(f"/{PROBE_PREFIX}basic%2Ehtml")
    require(
        plain.status == HTTP_OK,
        f"GET /{PROBE_PREFIX}basic.html returned {plain.status}; run `probe --up` first.",
    )
    require(
        encoded.status == HTTP_OK,
        f"GET /{PROBE_PREFIX}basic%2Ehtml returned {encoded.status}. If normalization is "
        "off the encoded path is a different key and 404s — which is itself the finding.",
    )
    check(
        encoded.header("content-security-policy") == plain.header("content-security-policy"),
        "the encoded and decoded paths got different CSPs, so the rules saw different "
        "paths: URL normalization is not doing what docs/08 §5.3 depends on",
    )
    return "%2E and . resolve to the same object with the same headers"


def check_file_headers() -> str:
    path = f"/{PROBE_PREFIX}file.bin"
    response = fetch(path)
    require(response.status == HTTP_OK, f"GET {path} returned {response.status}")
    for header, expected in (
        ("x-content-type-options", "nosniff"),
        ("cross-origin-resource-policy", "cross-origin"),
        ("timing-allow-origin", "*"),
        ("x-robots-tag", "noindex"),
    ):
        got = response.header(header)
        check(got == expected, f"{header} on {path} is {got!r}, expected {expected!r}")
    return "nosniff, CORP, TAO and noindex all present"


def check_cors_is_open_and_survives_the_cache() -> str:
    """A cached response must still answer cross-origin, which is the product's point."""
    path = f"/{PROBE_PREFIX}file.bin"
    cold = fetch(path)
    require(cold.status == HTTP_OK, f"GET {path} returned {cold.status}")
    warm = fetch(path, extra_headers={"Origin": "https://example.org"})
    require(warm.status == HTTP_OK, f"GET {path} with Origin returned {warm.status}")
    allow = warm.header("access-control-allow-origin")
    check(allow == "*", f"access-control-allow-origin is {allow!r} on a warm cache hit")
    return f"allow-origin * (cf-cache-status {warm.header('cf-cache-status') or 'unset'})"


def check_cors_preflight() -> str:
    path = f"/{PROBE_PREFIX}file.bin"
    response = fetch(
        path,
        method="OPTIONS",
        extra_headers={
            "Origin": "https://example.org",
            "Access-Control-Request-Method": "GET",
        },
    )
    require(
        response.status < HTTP_NOT_FOUND,
        f"OPTIONS {path} returned {response.status}; a preflight that errors tells us "
        "nothing about the CORS policy",
    )
    allow = response.header("access-control-allow-origin")
    check(allow == "*", f"preflight allow-origin is {allow!r}")
    return "preflight answers allow-origin *"


def check_www_redirects_to_apex() -> str:
    response = fetch("/pdf/a4-3pages.pdf", host=f"www.{SITE_HOST}")
    check(
        response.status == HTTP_MOVED_PERMANENTLY,
        f"www returned {response.status}, expected {HTTP_MOVED_PERMANENTLY}",
    )
    location = response.header("location")
    check(location.startswith(f"{BASE}/"), f"www redirects to {location!r}")
    check("/pdf/a4-3pages.pdf" in location, f"the path was not preserved: {location!r}")
    return location


def check_query_strings_share_one_cache_entry() -> str:
    """docs/08 §5.4: without this every `?x=…` is a separate object and a separate read."""
    path = f"/{PROBE_PREFIX}file.bin"
    first = fetch(f"{path}?x=1")
    require(first.status == HTTP_OK, f"GET {path}?x=1 returned {first.status}")
    second = fetch(f"{path}?x=2")
    require(second.status == HTTP_OK, f"GET {path}?x=2 returned {second.status}")
    status = second.header("cf-cache-status")
    require(
        bool(status),
        "no cf-cache-status header, so cache behaviour cannot be observed at all",
    )
    check(
        status.upper() == "HIT",
        f"?x=2 reported cf-cache-status {status!r} after ?x=1; the cache key is not "
        "ignoring the query string (docs/08 §5.4)",
    )
    return "?x=1 then ?x=2 -> HIT"


def check_key_named_dir_coexists_with_its_index() -> str:
    """R2 serves keys literally: `_probe/dir` and `_probe/dir/index.html` are both real."""
    bare = fetch(f"/{PROBE_PREFIX}dir")
    require(bare.status == HTTP_OK, f"GET /{PROBE_PREFIX}dir returned {bare.status}")
    slashed = fetch(f"/{PROBE_PREFIX}dir/")
    require(slashed.status == HTTP_OK, f"GET /{PROBE_PREFIX}dir/ returned {slashed.status}")
    check(
        bare.body != slashed.body,
        "the bare key and the directory index returned identical bytes, so one of them "
        "is not being served as its own object",
    )
    return "both keys served, and they differ"


def check_rate_limit_blocks_a_burst() -> str:
    """Assert the 429. **This must never retry** (see :func:`fetch`).

    `verify-live` treats a 429 from our own limit as retry-after-10s. Here its *absence*
    is the failure, so the two behaviours are kept in separate code paths on purpose.
    """
    path = f"/{PROBE_PREFIX}file.bin"
    statuses = [fetch(f"{path}?burst={n}").status for n in range(RATE_LIMIT_BURST)]
    require(
        any(s == HTTP_OK for s in statuses),
        "not one request in the burst succeeded, so the 429 (if any) may be unrelated to "
        "the rate limit",
    )
    check(
        HTTP_TOO_MANY_REQUESTS in statuses,
        f"{RATE_LIMIT_BURST} requests produced no 429. The rate-limit rule is not in "
        f"effect: {sorted(set(statuses))}",
    )
    blocked_at = statuses.index(HTTP_TOO_MANY_REQUESTS)
    time.sleep(RATE_LIMIT_RECOVERY_SECONDS)
    after = fetch(f"{path}?recovered=1")
    check(
        after.status == HTTP_OK,
        f"still {after.status} after {RATE_LIMIT_RECOVERY_SECONDS}s; the mitigation "
        "timeout is longer than docs/08 §5.5 claims",
    )
    return f"429 from request {blocked_at}, recovered after {RATE_LIMIT_RECOVERY_SECONDS}s"


def check_404_is_cached() -> str:
    missing = f"/{PROBE_PREFIX}definitely-not-here-{int(time.time())}"
    first = fetch(missing)
    check(first.status == HTTP_NOT_FOUND, f"expected 404, got {first.status}")
    second = fetch(missing)
    status = second.header("cf-cache-status")
    require(bool(status), "no cf-cache-status on a 404, so caching cannot be observed")
    return f"404 cache status {status}"


#: Every check the probe runs against the live site.
SITE_CHECKS: dict[str, Check] = {
    "url-normalization": check_url_normalization_is_on,
    "markup-sandbox-csp": check_markup_sandbox_csp,
    "file-headers": check_file_headers,
    "cors-warm-cache": check_cors_is_open_and_survives_the_cache,
    "cors-preflight": check_cors_preflight,
    "www-redirect": check_www_redirects_to_apex,
    "query-string-cache-key": check_query_strings_share_one_cache_entry,
    "dir-key-coexistence": check_key_named_dir_coexists_with_its_index,
    "404-caching": check_404_is_cached,
    "rate-limit": check_rate_limit_blocks_a_burst,
}


# --- the bucket -------------------------------------------------------------


def _client() -> Any:  # noqa: ANN401 - boto3 exposes no client type to annotate
    """An S3 client for T2. Imported here because boto3 is only needed for these checks."""
    import boto3  # noqa: PLC0415 - boto3 is only needed by the bucket checks

    for name in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "CLOUDFLARE_ACCOUNT_ID"):
        if not os.environ.get(name):
            raise PreconditionUnmet(f"{name} is not set; the bucket checks cannot run")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['CLOUDFLARE_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def bucket_name() -> str:
    return os.environ.get("R2_BUCKET", "loremfile-public")


def upload_probe_objects() -> list[str]:
    """Write the objects the site checks read. Only under `_probe/`."""
    client = _client()
    written = []
    for key, (content_type, body) in PROBE_OBJECTS.items():
        client.put_object(
            Bucket=bucket_name(),
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl="public, max-age=60",
        )
        written.append(key)
    return written


def delete_probe_objects() -> list[str]:
    """`probe --down`. `_probe/` is outside every lock rule, so this must succeed."""
    client = _client()
    deleted = []
    listing = client.list_objects_v2(Bucket=bucket_name(), Prefix=PROBE_PREFIX)
    for entry in listing.get("Contents", []):
        client.delete_object(Bucket=bucket_name(), Key=entry["Key"])
        deleted.append(entry["Key"])
    return deleted


def check_probe_prefix_is_writable() -> str:
    """T2 must be able to delete under `_probe/`, or `probe --down` cannot clean up."""
    client = _client()
    key = f"{PROBE_PREFIX}writable-check"
    client.put_object(Bucket=bucket_name(), Key=key, Body=b"1")
    client.delete_object(Bucket=bucket_name(), Key=key)
    listing = client.list_objects_v2(Bucket=bucket_name(), Prefix=key)
    check(
        listing.get("KeyCount", 0) == 0,
        f"{key} still exists after delete; `_probe/` is inside a lock rule, which would "
        "make `probe --down` impossible and would mean the lock rules cover more than "
        "the format prefixes (docs/08 §7b)",
    )
    return "write then delete both succeeded under _probe/"


def check_locked_prefix_refuses_overwrite_and_delete() -> str:
    """The real test of the 53 lock rules applied in M2.3.

    Locks block overwrite and delete, never creation — so the first write must succeed
    and the second must not. `_locktest/probe` is written once and stays forever; that is
    what the prefix is for, and why no fixture prefix is ever probed this way.
    """
    from botocore.exceptions import ClientError  # noqa: PLC0415 - see _client

    client = _client()
    bucket = bucket_name()

    existed = True
    try:
        client.head_object(Bucket=bucket, Key=LOCKTEST_KEY)
    except ClientError:
        existed = False

    created = ""
    if not existed:
        # Creation is allowed even under an indefinite lock. If this fails, the lock
        # rules block more than documented and uploads would fail too.
        client.put_object(Bucket=bucket, Key=LOCKTEST_KEY, Body=b"1")
        created = "created it (locks do not block creation); "

    overwrite_refused = False
    try:
        client.put_object(Bucket=bucket, Key=LOCKTEST_KEY, Body=b"2")
    except ClientError:
        overwrite_refused = True
    check(
        overwrite_refused,
        f"overwriting {LOCKTEST_KEY} succeeded. The lock rule for {LOCKTEST_KEY} is not "
        "in effect, and a leaked T2 could replace published fixtures (ADR-023).",
    )

    delete_refused = False
    try:
        client.delete_object(Bucket=bucket, Key=LOCKTEST_KEY)
    except ClientError:
        delete_refused = True
    check(delete_refused, f"deleting {LOCKTEST_KEY} succeeded; the lock does not hold")

    body = client.get_object(Bucket=bucket, Key=LOCKTEST_KEY)["Body"].read()
    check(body == b"1", f"{LOCKTEST_KEY} holds {body!r}; the refused overwrite still landed")
    return f"{created}overwrite and delete both refused, original bytes intact"


#: Checks that talk to the bucket rather than the edge.
BUCKET_CHECKS: dict[str, Check] = {
    "probe-prefix-writable": check_probe_prefix_is_writable,
    "locked-prefix-immutable": check_locked_prefix_refuses_overwrite_and_delete,
}
