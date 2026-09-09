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

import itertools
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
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

#: How long a rule may take to reach every edge after `infra.yml apply` (docs/11 §7.2b).
#: Bounded and stated on purpose: a generous deadline would turn the settle into the
#: vacuous pass it exists to catch, so it is short enough that a genuinely broken zone
#: still fails the run.
SETTLE_DEADLINE_SECONDS = 180
SETTLE_INTERVAL_SECONDS = 5

#: `cf-cache-status` values that mean the edge is willing to cache this response.
#: `DYNAMIC` means it is not — every unique request would be an origin read.
CACHEABLE_STATUSES = frozenset({"HIT", "MISS", "EXPIRED", "REVALIDATED", "UPDATING", "STALE"})
UNCACHEABLE_STATUSES = frozenset({"DYNAMIC", "BYPASS", "NONE", "UNKNOWN"})

#: `Age` only becomes non-zero once a whole second has passed at the edge.
AGE_SETTLE_SECONDS = 3
#: Each attempt may land on a cold edge node; one non-zero Age is proof, so try a few.
QUERY_STRING_ATTEMPTS = 6

#: The rate-limit rule: 300 requests / 10 s per IP per colo, mitigation timeout 10 s.
RATE_LIMIT_BURST = 600
RATE_LIMIT_RECOVERY_SECONDS = 12
RATE_LIMIT_PERIOD_SECONDS = 10
RATE_LIMIT_REQUESTS = 300
#: Enough concurrency to clear 30 requests/second. A sequential burst manages 12-20/s
#: and cannot provoke the rule at all, which is what made the first version unfalsifiable.
RATE_LIMIT_WORKERS = 48

#: Load is sustained for a duration, not a request count: a fixed count conflates rate
#: with coverage of the counting window, and run 5 showed that conflation matters.
RATE_LIMIT_SUSTAIN_SECONDS = 25

#: Held constant across runs, at the rate that fired in run 6. The open question is
#: *consistency at a given rate*; varying the rate measures the probability curve instead
#: and answers neither. If three runs fire here, consistency is established at this rate,
#: and the 45-69/s non-firing becomes a separate documented property — approximate below
#: some rate — rather than an unexplained intermittency.
RATE_LIMIT_TARGET_RPS = 262
#: Outside this tolerance the run is a precondition failure: the load was not the load
#: the cross-run comparison is about.
RATE_LIMIT_RATE_TOLERANCE = 0.2

#: Cloudflare's trace endpoint on this zone. Reports the `ip` and `colo` the edge sees —
#: exactly the two characteristics the rule counts on.
TRACE_PATH = "/cdn-cgi/trace"
TRACE_SAMPLES = 12

HTTP_OK = 200
HTTP_MOVED_PERMANENTLY = 301
HTTP_NOT_FOUND = 404
HTTP_TOO_MANY_REQUESTS = 429

#: What a CORS preflight may answer. Anything else — including a redirect, which the
#: browser would not follow for a preflight — means the policy was not observed.
PREFLIGHT_STATUSES = frozenset({200, 204})


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


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Return the redirect itself instead of following it.

    `urlopen` follows redirects by default, which made the www check assert against the
    *apex root* — a correct 404 while no site is uploaded — and report that www was
    broken. A probe that examines redirects must see them.
    """

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirects)


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
        with _OPENER.open(request, timeout=timeout) as response:
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


def settle(
    description: str,
    once: Callable[[], Fetched],
    appeared: Callable[[Fetched], bool],
    *,
    deadline: int = SETTLE_DEADLINE_SECONDS,
) -> Fetched:
    """Poll until the expected thing appears, or fail saying it never did.

    `infra.yml apply` returns before its rules have reached every edge, so a probe run
    immediately afterwards sees the old configuration and reports a zone-wide outage.
    This is the bounded wait for that, and it keeps the two findings apart:

    * **never appeared within N** — propagation, or a rule that was never applied. Raised
      as a precondition failure, naming the deadline.
    * **appeared and was wrong** — a real misconfiguration, raised by whatever the caller
      asserts afterwards.

    The predicate must be *weaker* than the assertion that follows it, or this would wait
    for the answer it wants and mask a wrong one. Deliberately not used by the rate-limit
    check, which must observe a 429 on a single unretried request.
    """
    started = time.monotonic()
    last = once()
    while not appeared(last):
        waited = time.monotonic() - started
        if waited >= deadline:
            raise PreconditionUnmet(
                f"{description} never appeared within {deadline}s "
                f"(last response: status {last.status}). Either the rule has not "
                "propagated or it was never applied — this is not a wrong value, which "
                "would have been reported as a failed assertion instead."
            )
        time.sleep(SETTLE_INTERVAL_SECONDS)
        last = once()
    return last


#: `cf-cache-status` is **not** a sanctioned instrument for asserting cache behaviour.
#: Edge nodes within a colo do not share a local cache, so a MISS means only that *this*
#: node had not seen the object — it flipped passing checks to failing across runs 3-6
#: with nothing changed in between. `Age` is positive evidence: a non-zero value can only
#: come from an entry an earlier request populated. A test fails if any check reads the
#: header directly, so the instrument is unavailable rather than discouraged.
CACHE_SAMPLES = 6


def served_from_cache(
    path: str, *, samples: int = CACHE_SAMPLES, expect_status: int = HTTP_OK
) -> tuple[bool, str]:
    """Is `path` served from the edge cache? The only sanctioned way to ask.

    Populates the entry, waits long enough for `Age` to become non-zero, then samples.
    **One non-zero `Age` is proof**; absence across every sample is evidence but not
    proof, since each request may land on a cold node. Returns the verdict and what was
    observed, so a caller's failure message can carry it.
    """
    populate = fetch(path)
    require(
        populate.status == expect_status,
        f"GET {path} returned {populate.status}, expected {expect_status}; there is "
        "nothing to observe, and an absent Age would mean only that",
    )
    time.sleep(AGE_SETTLE_SECONDS)

    observations = []
    for _ in range(samples):
        response = fetch(path)
        age = response.header("age")
        observations.append(f"age={age or '-'}")
        if age.isdigit() and int(age) > 0:
            return True, f"Age {age}s after {len(observations)} sample(s)"
        time.sleep(1)
    return False, f"no non-zero Age in {samples} samples ({', '.join(observations)})"


@dataclass
class Result:
    name: str
    state: str  # pass | fail
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
    response = settle(
        f"a Content-Security-Policy on {encoded}",
        lambda: fetch(encoded),
        lambda r: r.status == HTTP_OK and bool(r.header("content-security-policy")),
    )
    require(
        response.status == HTTP_OK,
        f"GET {encoded} returned {response.status}; with nothing served there, an absent "
        "CSP proves nothing about the header rule or about URL normalization. Run "
        "`probe --up` first.",
    )
    csp = response.header("content-security-policy")
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
    # Requiring the header to exist before comparing is the whole difference between a
    # real check and a tautology: with no header rule at all both sides are "" and the
    # comparison passes while proving nothing. Same shape as 404-caching passing on
    # DYNAMIC — a check that compares two things without requiring either to be there.
    require(
        bool(plain.header("content-security-policy")),
        f"no Content-Security-Policy on /{PROBE_PREFIX}basic.html at all, so comparing it "
        "with the encoded path would compare two absent headers and pass",
    )
    check(
        encoded.header("content-security-policy") == plain.header("content-security-policy"),
        "the encoded and decoded paths got different CSPs, so the rules saw different "
        "paths: URL normalization is not doing what docs/08 §5.3 depends on",
    )
    return "%2E and . resolve to the same object with the same headers"


def check_file_headers() -> str:
    path = f"/{PROBE_PREFIX}file.bin"
    response = settle(
        f"the file header rule on {path}",
        lambda: fetch(path),
        lambda r: r.status == HTTP_OK and bool(r.header("x-content-type-options")),
    )
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
    """A **cached** response must still answer cross-origin. Both halves are asserted.

    The cache half is measured with `Age` via :func:`served_from_cache`. It previously
    asserted `cf-cache-status == HIT`, inheriting the flaw the query-string check had
    already been fixed for — a status that flips with edge-node locality rather than with
    configuration. Found by sweeping every check rather than by another failing run.
    """
    path = f"/{PROBE_PREFIX}file.bin"
    cached, evidence = served_from_cache(path)
    check(
        cached,
        f"{path} is never served from cache, so this proves nothing about CORS surviving "
        f"the cache ({evidence})",
    )
    warm = fetch(path, extra_headers={"Origin": "https://example.org"})
    require(warm.status == HTTP_OK, f"GET {path} with Origin returned {warm.status}")
    allow = warm.header("access-control-allow-origin")
    check(allow == "*", f"access-control-allow-origin is {allow!r} on a cached response")
    return f"allow-origin * on a cached response ({evidence})"


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
        response.status in PREFLIGHT_STATUSES,
        f"OPTIONS {path} returned {response.status}; a preflight that is redirected or "
        "errors tells us nothing about the CORS policy",
    )
    allow = response.header("access-control-allow-origin")
    check(allow == "*", f"preflight allow-origin is {allow!r}")
    return "preflight answers allow-origin *"


def check_www_redirects_to_apex() -> str:
    response = settle(
        "a 301 from the www host",
        lambda: fetch("/pdf/a4-3pages.pdf", host=f"www.{SITE_HOST}"),
        lambda r: r.status == HTTP_MOVED_PERMANENTLY,
    )
    check(
        response.status == HTTP_MOVED_PERMANENTLY,
        f"www returned {response.status}, expected {HTTP_MOVED_PERMANENTLY}",
    )
    location = response.header("location")
    check(location.startswith(f"{BASE}/"), f"www redirects to {location!r}")
    check("/pdf/a4-3pages.pdf" in location, f"the path was not preserved: {location!r}")
    return location


def check_query_strings_share_one_cache_entry() -> str:
    """docs/08 §5.4 / ADR-013: `?anything` must hit the entry the bare path populated.

    **Measured with `Age`, not `cf-cache-status`.** The status is unreliable for this:
    the check passed on run 3 and failed on run 4 unchanged, because edge nodes within a
    colo do not share a local cache, so a MISS says only "this node had not seen it". A
    non-zero `Age` on `?x=2` is positive evidence — it can only have come from an entry
    populated by an earlier request, and since the earlier request used a different query
    string, the query string is not part of the cache key.

    One non-zero `Age` proves it. Several attempts are made because each may land on a
    cold node, and a cold node is not a finding; exhausting them without a single hit is.
    """
    path = f"/{PROBE_PREFIX}file.bin"
    populate = fetch(f"{path}?x=1")
    require(populate.status == HTTP_OK, f"GET {path}?x=1 returned {populate.status}")
    # Long enough that a served-from-cache response reports a whole second of Age.
    time.sleep(AGE_SETTLE_SECONDS)

    observations = []
    for attempt in range(QUERY_STRING_ATTEMPTS):
        response = fetch(f"{path}?x={attempt + 2}")
        require(response.status == HTTP_OK, f"GET {path}?x= returned {response.status}")
        age = response.header("age")
        observations.append(f"age={age or '-'}")
        if age.isdigit() and int(age) > 0:
            return (
                f"?x={attempt + 2} served with Age {age}s from the entry ?x=1 populated: "
                "the query string is not part of the cache key"
            )
        time.sleep(1)

    check(
        False,
        f"no query-string request reported a non-zero Age in {QUERY_STRING_ATTEMPTS} "
        f"attempts ({', '.join(observations)}). Either the cache key includes the query "
        "string (docs/08 §5.4 would then be wrong, and every `?x=` is a separate R2 read) "
        "or every attempt landed on a cold edge node.",
    )
    raise AssertionError("unreachable")  # pragma: no cover


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


def deployed_rate_limit_rule() -> dict[str, Any] | None:
    """The zone's own rate-limit rule, read zone-scoped (T1 can do this).

    Read back before the burst so that "no 429" can be attributed. Without it the check
    cannot tell a rule that is missing from a rule that is present and simply was not
    provoked, and it previously concluded the former from the latter.
    """
    from loremfile.infra.cloudflare_api import Client, CloudflareError  # noqa: PLC0415

    try:
        client = Client.from_env()
        response = client.get(f"/zones/{client.zone_id}/rulesets/phases/http_ratelimit/entrypoint")
    except CloudflareError:
        return None
    if not response.ok:
        return None
    for rule in (response.result or {}).get("rules") or []:
        if rule.get("ratelimit"):
            return dict(rule)
    return None


def check_rate_limit_rule_is_deployed() -> str:
    """The rule exists, with the characteristics docs/08 §5.5 specifies.

    Separated from the burst deliberately: this half is a fact about configuration and
    can be asserted whatever load the runner can generate. A missing rule here is a real
    finding rather than an inference from silence.
    """
    rule = deployed_rate_limit_rule()
    require(
        rule is not None,
        "could not read the http_ratelimit entrypoint (no credentials, or the API "
        "refused). Without it, an absent 429 cannot be attributed to anything.",
    )
    limit = (rule or {}).get("ratelimit") or {}
    characteristics = set(limit.get("characteristics") or [])
    check(
        characteristics == {"cf.colo.id", "ip.src"},
        f"rate-limit characteristics are {sorted(characteristics)}; docs/08 §5.5 requires "
        "exactly cf.colo.id and ip.src, and Cloudflare documents cf.colo.id as mandatory",
    )
    check(
        limit.get("period") == RATE_LIMIT_PERIOD_SECONDS,
        f"period is {limit.get('period')}s, expected {RATE_LIMIT_PERIOD_SECONDS}s",
    )
    check(
        limit.get("requests_per_period") == RATE_LIMIT_REQUESTS,
        f"threshold is {limit.get('requests_per_period')}, expected {RATE_LIMIT_REQUESTS}",
    )
    return f"{limit.get('requests_per_period')} requests / {limit.get('period')}s, per IP per colo"


def observed_identity() -> dict[str, set[str]]:
    """The `ip` and `colo` the edge attributes our requests to, sampled concurrently.

    The rule counts per `(ip.src, cf.colo.id)`. If a runner's concurrent connections
    egress from more than one address, or land in more than one data centre, no single
    counter ever sees the whole burst — and an absent 429 says nothing about the rule.
    Sampling this makes that explanation observable rather than speculative.
    """
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    with ThreadPoolExecutor(max_workers=TRACE_SAMPLES) as pool:
        pages = list(pool.map(lambda _n: fetch(TRACE_PATH), range(TRACE_SAMPLES)))

    seen: dict[str, set[str]] = {"ip": set(), "colo": set()}
    for page in pages:
        for line in page.body.decode("utf-8", "replace").splitlines():
            field, _, value = line.partition("=")
            if field in seen and value:
                seen[field].add(value)
    return seen


def _sustained(make_path: Callable[[int], str]) -> tuple[list[int], dict[str, int], float]:
    """Request at RATE_LIMIT_TARGET_RPS for RATE_LIMIT_SUSTAIN_SECONDS.

    Paced rather than as-fast-as-possible: the question is whether the rule fires
    consistently *at a given rate*, so the rate is the controlled variable. Enough
    workers to reach the target on a slow runner, each sleeping to hold its share.
    """
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    deadline = time.monotonic() + RATE_LIMIT_SUSTAIN_SECONDS
    interval = RATE_LIMIT_WORKERS / RATE_LIMIT_TARGET_RPS
    counter = itertools.count()
    statuses: list[int] = []
    cache: dict[str, int] = {}
    lock = threading.Lock()

    def worker(_n: int) -> None:
        while time.monotonic() < deadline:
            began = time.monotonic()
            response = fetch(make_path(next(counter)))
            label = response.header("cf-cache-status").upper() or "none"
            with lock:
                statuses.append(response.status)
                cache[label] = cache.get(label, 0) + 1
            if response.status == HTTP_TOO_MANY_REQUESTS:
                return
            pause = interval - (time.monotonic() - began)
            if pause > 0:
                time.sleep(pause)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=RATE_LIMIT_WORKERS) as pool:
        list(pool.map(worker, range(RATE_LIMIT_WORKERS)))
    elapsed = max(time.monotonic() - started, 0.001)
    return statuses, cache, len(statuses) / elapsed


def check_rate_limit_blocks_a_burst() -> str:
    """Assert the 429 under load sustained past the counting window.

    **Never retries** (see :func:`fetch`), and never concludes from load it failed to
    generate — which now includes load the edge attributed to more than one identity.

    Run 4 blocked at request 547 of 600 at 156 req/s. Run 5 sent 600 at 69 req/s and 600
    unique-path requests at 45 req/s, both above the 30 req/s threshold, and neither was
    blocked — and the slower run had *more* headroom after crossing the threshold (4.3 s
    against 1.9 s), so window coverage does not explain the difference. Two variables were
    unmeasured and both now are: load is sustained for a fixed **duration** rather than a
    fixed count, and the `ip`/`colo` the edge sees is sampled, because the counter is per
    `(ip.src, cf.colo.id)` and a split identity means no counter saw the whole burst.

    **How to read the result. Agreed before the run, so that neither reading is chosen
    after seeing the outcome** — the same discipline as the matrix fixed before run 4:

    (a) **Identity splits across IPs or colos.** Explains both runs. The rule works; the
        probe could not test it. Fix the probe to hold one identity, or account for the
        split, and retest. **Not a finding about Cloudflare.**

    (b) **Identity is consistent and still no 429.** The branch that matters: the limit is
        *approximate* at these rates rather than a hard bound. Cloudflare's rate-limiting
        counters are distributed, and approximate enforcement is a documented property of
        that design rather than a defect. If this is the answer, RISK-22 changes
        materially — **neither** cost control is a hard bound, and docs/19 §3's scenarios
        rest only on the manual escalations in the runbook §7.4 (ASN blocks, Under Attack,
        disabling the custom domain). That must be explicit before M5.1, and M4.4's deploy
        gate should reference it.

    (c) **Identity is consistent and a 429 fires.** One pass does not establish
        consistency after two failures. **Three consecutive runs** before recording it as
        consistent.

    A fourth case is mechanical rather than interpretive: if the rule read-back fails, no
    attribution is possible at all and nothing may be drawn from the load.

    Whichever branch lands, it is brought to the owner before the rule or the docs change.
    """
    identity = observed_identity()
    require(
        len(identity["ip"]) == 1 and len(identity["colo"]) == 1,
        f"the edge attributed this run to ip={sorted(identity['ip'])} "
        f"colo={sorted(identity['colo'])}. The rule counts per (ip.src, cf.colo.id), so a "
        "split identity means no single counter saw the whole load. **This is not "
        "evidence about the rule.**",
    )
    where = f"ip={next(iter(identity['ip']))} colo={next(iter(identity['colo']))}"

    path = f"/{PROBE_PREFIX}file.bin"
    cached_statuses, cached_cache, cached_rate = _sustained(lambda n: f"{path}?burst={n}")
    required = RATE_LIMIT_REQUESTS / RATE_LIMIT_PERIOD_SECONDS
    low = RATE_LIMIT_TARGET_RPS * (1 - RATE_LIMIT_RATE_TOLERANCE)
    high = RATE_LIMIT_TARGET_RPS * (1 + RATE_LIMIT_RATE_TOLERANCE)
    require(
        low <= cached_rate <= high,
        f"sustained {cached_rate:.0f} requests/second, outside {low:.0f}-{high:.0f}/s. "
        f"The cross-run comparison is about consistency **at {RATE_LIMIT_TARGET_RPS}/s**, "
        "so a different rate is a different experiment. **Not evidence about the rule.**",
    )
    check(
        required < RATE_LIMIT_TARGET_RPS,
        f"the target rate is at or below the rule's {required:.0f}/s threshold; the "
        "experiment cannot provoke it by construction",
    )
    if HTTP_TOO_MANY_REQUESTS in cached_statuses:
        blocked = cached_statuses.index(HTTP_TOO_MANY_REQUESTS)
        _recover()
        return (
            f"429 after {blocked} cached requests at {cached_rate:.0f}/s over "
            f"{RATE_LIMIT_SUSTAIN_SECONDS}s ({where}, cache {cached_cache})"
        )

    stamp = int(time.time())
    unique_statuses, unique_cache, unique_rate = _sustained(
        lambda n: f"/{PROBE_PREFIX}absent-{stamp}-{n}"
    )
    evidence = (
        f"{where}; cached {len(cached_statuses)} req at {cached_rate:.0f}/s "
        f"cache={cached_cache}; unique {len(unique_statuses)} req at {unique_rate:.0f}/s "
        f"cache={unique_cache}"
    )
    check(
        HTTP_TOO_MANY_REQUESTS in unique_statuses,
        f"no 429 from {RATE_LIMIT_SUSTAIN_SECONDS}s of sustained load in either shape, "
        f"both above {required:.0f}/s, from a single identity. Run 4 blocked at request "
        "547, so the rule *can* enforce — this is about consistency, not deployment. "
        f"Evidence: {evidence}",
    )
    _recover()
    return (
        "429 only from the uncacheable load: edge-served requests do not reach the "
        f"rate-limit counter. {evidence}"
    )


def _recover() -> None:
    """Wait out the mitigation timeout so later checks are not blocked by our own burst."""
    time.sleep(RATE_LIMIT_RECOVERY_SECONDS)
    after = fetch(f"/{PROBE_PREFIX}file.bin?recovered=1")
    check(
        after.status == HTTP_OK,
        f"still {after.status} after {RATE_LIMIT_RECOVERY_SECONDS}s; the mitigation "
        "timeout is longer than docs/08 §5.5 claims",
    )


def check_404_caching_is_still_absent() -> str:
    """404s are not served from cache — asserted with `Age`, not `cf-cache-status`.

    **The claim is under measurement.** `docs/03` §3 and ADR-026 were written on
    `MISS/MISS` readings, which are not evidence: a MISS means only that *this* edge node
    had not seen it. Run 6 then reported `first=MISS second=HIT age=0`, equally
    uninformative in the other direction, since `Age 0` does not establish an earlier
    entry either.

    **Pre-registered before any of it was run**, so that a distributed edge cannot be
    rounded to whichever answer suits. **Three runs of `CACHE_SAMPLES` samples each — 18
    observations.** A run is *positive* if any sample reports a non-zero `Age`, and `K` is
    the sample number at which that first happened (1..6).

    (a) **404s are cached.** 3/3 runs positive, and `K <= 2` in at least two of them.
        `docs/03` §3's **original** three-minute claim was closer to right than the
        correction that replaced it; ADR-026's premise flips; RISK-22 **improves**,
        because both cost controls then exist. To be stated plainly, not softened.

    (b) **404s are not cached.** 0/3 runs positive — no non-zero `Age` in any of the 18
        samples. The current statement stands, now on evidence rather than on a
        `MISS/MISS` reading.

    (c) **Cached per edge node, with no promotion.** Anything else: 1/3 or 2/3 runs
        positive, or 3/3 positive but needing `K >= 3` in two or more of them. The most
        likely outcome on a distributed edge, and the one that invites rounding. Decided
        in advance to mean: **caching exists but is weak** — it bounds repeat requests
        only on nodes that have already seen the path, so it is not a control the cost
        model may lean on, and `docs/19` §3's scenarios are unchanged.

    In every branch, `docs/03` §3, ADR-026's premise, RISK-22 and the changelog's
    verified list are revised **together, in one pull request**, on the evidence.
    """
    missing = f"/{PROBE_PREFIX}definitely-not-here-{int(time.time())}"
    first = fetch(missing)
    check(first.status == HTTP_NOT_FOUND, f"expected 404, got {first.status}")

    cached, evidence = served_from_cache(missing, expect_status=HTTP_NOT_FOUND)
    check(
        not cached,
        f"a repeated 404 was served from cache ({evidence}) — the first measurement of "
        "this with an instrument that can prove it. This changes the premise of docs/03 "
        "§3 and ADR-026; revise the cost model. ADR-026's conclusion does not depend on "
        "the premise, so a corrected premise is not a reason to revisit the decision.",
    )
    return f"404s not served from cache ({evidence})"


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
    "404-caching-absent": check_404_caching_is_still_absent,
    "rate-limit-rule": check_rate_limit_rule_is_deployed,
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
