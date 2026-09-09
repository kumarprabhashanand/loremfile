"""M2.4: the probe must fail loudly rather than pass vacuously.

Every assertion in `probe.py` can pass for the wrong reason, and this file is mostly
about that. The clearest case is the sandbox CSP on `/_probe/basic%2Ehtml`: if the
request 404s there is no CSP, no header, and nothing to assert on — and a naive check
reports "header absent" without being able to tell *the rule did not fire* from
*nothing was there*. Same shape as a `container.image` that resolves to an empty string:
the job runs, the check is green, nothing was tested.

So each check states its preconditions, an unmet precondition is a **failure**, and the
tests below drive each check with a 404 to prove it.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import time as _real_time
from typing import Any

import pytest

from loremfile.infra import probe
from loremfile.infra.probe import CheckFailed, Fetched, PreconditionUnmet


@pytest.fixture(autouse=True)
def _instant_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `settle` poll without wall-clock cost.

    Not a convenience: without it every check that settles waits out the real 180-second
    deadline in the unit tests, which is how this file first hung. The deadline itself is
    asserted separately in `test_settle_is_bounded_and_names_the_deadline`.
    """
    monkeypatch.setattr(probe.time, "sleep", lambda _s: None)
    ticks = iter(range(0, 10_000, 30))
    monkeypatch.setattr(probe.time, "monotonic", lambda: float(next(ticks)))


OK_HEADERS = {
    "content-security-policy": "sandbox; default-src 'none'",
    "cf-cache-status": "HIT",
    "access-control-allow-origin": "*",
    "x-content-type-options": "nosniff",
    "cross-origin-resource-policy": "cross-origin",
    "timing-allow-origin": "*",
    "x-robots-tag": "noindex",
}


def responder(
    monkeypatch: pytest.MonkeyPatch, answer: Any, *, record: list[str] | None = None
) -> None:
    def fake(path: str, **kwargs: Any) -> Fetched:
        if record is not None:
            record.append(path)
        return answer(path, **kwargs) if callable(answer) else answer

    monkeypatch.setattr(probe, "fetch", fake)


def everything_404(_path: str, **_kwargs: Any) -> Fetched:
    return Fetched(status=404, headers={}, body=b"")


def everything_ok(path: str, **_: Any) -> Fetched:
    return Fetched(status=200, headers=dict(OK_HEADERS), body=path.encode())


#: Every check that reads the edge. Each must refuse to evaluate against a 404.
#: `404-caching-absent` is excluded: a 404 is its *subject*, not a missing precondition,
#: so driving it against one tests nothing. Every other edge check must refuse.
EDGE_CHECKS = sorted(
    set(probe.SITE_CHECKS) - {"www-redirect", "404-caching-absent", "rate-limit", "rate-limit-rule"}
)


@pytest.mark.parametrize("name", EDGE_CHECKS)
def test_no_check_passes_when_nothing_is_served(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The heart of it: a 404 must be a failure, not an absent header.

    Written as a sweep rather than one test per check, so a check added later is covered
    without anyone remembering to add a test for it.
    """
    responder(monkeypatch, everything_404)
    report = probe.run_checks({name: probe.SITE_CHECKS[name]})
    assert report.results[0].state == "fail", f"{name} passed against a 404"
    assert "precondition unmet" in report.results[0].detail, (
        f"{name} failed, but not for the right reason: {report.results[0].detail}"
    )
    assert not report.ok


def test_a_precondition_failure_is_never_reported_as_a_skip() -> None:
    """A skip would be counted as 'not a failure', which is how this rots."""

    def unmet() -> str:
        raise PreconditionUnmet("nothing served")

    report = probe.run_checks({"x": unmet})
    assert report.results[0].state == "fail"
    assert not report.ok


def test_the_csp_check_distinguishes_absent_from_unserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Served but no header is a real finding; not served is a precondition failure.

    They must not read the same, or the rule's absence and the object's absence become
    the same result.
    """
    responder(monkeypatch, Fetched(status=200, headers={}, body=b"x"))
    with pytest.raises(PreconditionUnmet) as served_no_header:
        probe.check_markup_sandbox_csp()
    assert "status 200" in str(served_no_header.value), (
        "served-but-no-header must be visibly different from nothing-served"
    )

    responder(monkeypatch, everything_404)
    with pytest.raises(PreconditionUnmet) as unserved:
        probe.check_markup_sandbox_csp()
    assert "status 404" in str(unserved.value)


def test_the_sandbox_csp_must_not_permit_script(monkeypatch: pytest.MonkeyPatch) -> None:
    headers = {**OK_HEADERS, "content-security-policy": "sandbox; script-src 'self'"}
    responder(monkeypatch, Fetched(status=200, headers=headers, body=b"x"))
    with pytest.raises(CheckFailed, match="script-src"):
        probe.check_markup_sandbox_csp()


# --- url normalization ------------------------------------------------------


def test_normalization_check_fails_when_the_encoded_path_404s(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If normalization is off, `%2E` is a different key and 404s — that is the finding."""

    def answer(path: str, **_: Any) -> Fetched:
        if "%2E" in path:
            return Fetched(status=404, headers={}, body=b"")
        return everything_ok(path)

    responder(monkeypatch, answer)
    report = probe.run_checks({"n": probe.check_url_normalization_is_on})
    assert report.results[0].state == "fail"
    assert "normalization is off" in report.results[0].detail


def test_normalization_check_fails_when_the_two_paths_get_different_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def answer(path: str, **_: Any) -> Fetched:
        csp = "" if "%2E" in path else "sandbox; default-src 'none'"
        return Fetched(status=200, headers={"content-security-policy": csp}, body=b"x")

    responder(monkeypatch, answer)
    with pytest.raises(CheckFailed, match="URL normalization"):
        probe.check_url_normalization_is_on()


# --- rate limit -------------------------------------------------------------


def one_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `observed_identity` report a single ip and colo, as a real run usually does."""
    monkeypatch.setattr(
        probe, "observed_identity", lambda: {"ip": {"203.0.113.7"}, "colo": {"LHR"}}
    )


#: Captured before the autouse fixture replaces it, so the duration loop can be timed.
REAL_MONOTONIC = _real_time.monotonic


def short_load(monkeypatch: pytest.MonkeyPatch, seconds: float = 0.05) -> None:
    """A real clock, briefly. `_sustained` loops on wall time, so the fast-advancing
    clock the settle tests use would make it exit before issuing a single request."""
    monkeypatch.setattr(probe.time, "monotonic", REAL_MONOTONIC)
    monkeypatch.setattr(probe, "RATE_LIMIT_SUSTAIN_SECONDS", seconds)
    monkeypatch.setattr(probe, "RATE_LIMIT_WORKERS", 2)
    # A target above the rule's threshold, and a band wide enough that whatever rate a
    # fake fetch achieves satisfies the precondition. The band itself is asserted
    # separately in test_a_rate_outside_the_band_is_a_precondition_failure.
    monkeypatch.setattr(probe, "RATE_LIMIT_TARGET_RPS", 40)
    monkeypatch.setattr(probe, "RATE_LIMIT_RATE_TOLERANCE", 1e9)


def test_a_split_identity_is_a_precondition_not_a_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The counter is per (ip.src, cf.colo.id): split load never reaches one counter.

    Run 5 produced no 429 at rates that should have triggered, and this was one of two
    unmeasured variables. Measuring it means the run can say "I could not test this"
    instead of "the rule does not work".
    """
    monkeypatch.setattr(
        probe,
        "observed_identity",
        lambda: {"ip": {"203.0.113.7", "203.0.113.8"}, "colo": {"LHR"}},
    )
    responder(monkeypatch, everything_ok)
    report = probe.run_checks({"rate-limit": probe.check_rate_limit_blocks_a_burst})
    detail = report.results[0].detail
    assert "precondition unmet" in detail
    assert "split identity" in detail
    assert "not evidence about the rule" in detail


def test_the_rate_limit_check_asserts_the_429(monkeypatch: pytest.MonkeyPatch) -> None:
    """Its absence is the failure, and the message must not overstate what it means."""
    one_identity(monkeypatch)
    short_load(monkeypatch)
    responder(monkeypatch, everything_ok)
    with pytest.raises(CheckFailed) as failure:
        probe.check_rate_limit_blocks_a_burst()
    message = str(failure.value)
    assert "no 429" in message
    assert "consistency, not deployment" in message, (
        "run 4 proved the rule can enforce; this must not read as 'the rule is inert'"
    )


def test_the_rate_limit_check_passes_when_the_limit_fires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    one_identity(monkeypatch)
    short_load(monkeypatch)
    responder(monkeypatch, Fetched(status=429, headers={}, body=b""))
    monkeypatch.setattr(probe, "_recover", lambda: None)
    assert "429 after" in probe.check_rate_limit_blocks_a_burst()


def test_load_is_sustained_by_duration_not_by_count() -> None:
    """A fixed count conflates rate with window coverage; run 5 is why that matters."""
    source = textwrap.dedent(inspect.getsource(probe._sustained))
    assert "RATE_LIMIT_SUSTAIN_SECONDS" in source
    assert "deadline" in source
    assert probe.RATE_LIMIT_SUSTAIN_SECONDS > probe.RATE_LIMIT_PERIOD_SECONDS, (
        "the load must outlast the counting window, or it can end before enforcement"
    )


def test_identity_is_sampled_from_our_own_zone() -> None:
    """No third-party service: /cdn-cgi/trace is served by Cloudflare on this zone."""
    assert probe.TRACE_PATH == "/cdn-cgi/trace"
    assert probe.TRACE_SAMPLES > 1, "one sample cannot reveal a split identity"


def test_fetch_has_no_retry_logic() -> None:
    """`verify-live` retries a 429; the probe asserts it. Separate code paths, on purpose.

    Checked against the AST rather than the text. The first version of this test grepped
    the source and failed on `fetch`'s own docstring, which explains the rule it was
    testing — exactly the false positive that moved the M3.4 generator-hygiene guard from
    grep to AST. A prose mention is not a retry; a loop or a sleep is.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(probe.fetch)))
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)

    loops = [n for n in ast.walk(function) if isinstance(n, ast.For | ast.While)]
    assert not loops, "probe.fetch loops; it must issue exactly one request"

    sleeps = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "sleep"
    ]
    assert not sleeps, "probe.fetch sleeps, which only makes sense as a retry"


def test_the_retry_guard_would_notice_a_loop() -> None:
    """Negative control (AGENTS.md): a guard nobody has seen fail proves nothing."""
    source = textwrap.dedent(
        """
        def fetch(path):
            for attempt in range(3):
                result = send(path)
            return result
        """
    )
    function = ast.parse(source).body[0]
    assert [n for n in ast.walk(function) if isinstance(n, ast.For | ast.While)]


# --- query string and cache -------------------------------------------------


def test_query_string_check_proves_the_shared_entry_with_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One non-zero Age is proof; it cannot arise except from an entry already populated."""

    def answer(path: str, **_: Any) -> Fetched:
        age = "7" if "x=2" in path else "0"
        return Fetched(status=200, headers={"cf-cache-status": "HIT", "age": age}, body=b"x")

    responder(monkeypatch, answer)
    detail = probe.check_query_strings_share_one_cache_entry()
    assert "Age 7s" in detail


def test_query_string_check_reports_every_observation_when_it_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure has to say what it saw, or the next run repeats the same ambiguity.

    A cold edge node and a query-string-keyed cache both produce no Age; the check cannot
    separate them from one sample, so it reports all of them and says so.
    """
    responder(monkeypatch, Fetched(status=200, headers={"cf-cache-status": "MISS"}, body=b"x"))
    with pytest.raises(CheckFailed) as failure:
        probe.check_query_strings_share_one_cache_entry()
    message = str(failure.value)
    assert f"in {probe.QUERY_STRING_ATTEMPTS} attempts" in message
    assert "cold edge node" in message, "the benign explanation must stay on the record"


def test_the_query_string_check_does_not_rely_on_cache_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cf-cache-status passed run 3 and failed run 4 unchanged; Age is the instrument now.

    A HIT with no Age must not be enough to pass, or the flaky measurement is back.
    """
    responder(monkeypatch, Fetched(status=200, headers={"cf-cache-status": "HIT"}, body=b"x"))
    with pytest.raises(CheckFailed):
        probe.check_query_strings_share_one_cache_entry()


def test_dir_coexistence_fails_when_both_keys_return_the_same_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responder(monkeypatch, Fetched(status=200, headers={}, body=b"same"))
    with pytest.raises(CheckFailed, match="identical bytes"):
        probe.check_key_named_dir_coexists_with_its_index()


# --- report -----------------------------------------------------------------


def test_one_failure_fails_the_report() -> None:
    report = probe.run_checks(
        {"good": lambda: "fine", "bad": lambda: (_ for _ in ()).throw(CheckFailed("no"))}
    )
    assert not report.ok
    assert "1 failed" in report.render()


def test_an_unexpected_error_is_a_failure_not_a_crash() -> None:
    report = probe.run_checks({"boom": lambda: (_ for _ in ()).throw(RuntimeError("x"))})
    assert report.results[0].state == "fail"
    assert "RuntimeError" in report.results[0].detail


def test_probe_only_ever_writes_outside_fixture_prefixes() -> None:
    """docs/03 §7.1: `_probe/` and `_locktest/` are not fixture paths."""
    for key in probe.PROBE_OBJECTS:
        assert key.startswith(probe.PROBE_PREFIX)
    assert probe.LOCKTEST_KEY.startswith("_locktest/")


# --- settling ---------------------------------------------------------------


def test_settle_returns_as_soon_as_the_thing_appears() -> None:
    attempts = []

    def once() -> Fetched:
        attempts.append(1)
        return Fetched(status=200 if len(attempts) > 2 else 404, headers={}, body=b"")

    result = probe.settle("a 200", once, lambda r: r.status == 200)
    assert result.status == 200
    assert len(attempts) == 3, "settle must stop polling once the predicate holds"


def test_settle_is_bounded_and_names_the_deadline() -> None:
    """An unbounded wait would be the vacuous pass this whole module exists to prevent."""
    with pytest.raises(PreconditionUnmet, match="never appeared within 180s"):
        probe.settle("a 200", lambda: Fetched(status=404, headers={}, body=b""), lambda _r: False)


def test_never_appeared_and_appeared_but_wrong_are_different_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The distinction the settle exists to preserve.

    Propagation and misconfiguration need different responses, so they must not produce
    the same message.
    """
    responder(monkeypatch, everything_404)
    never = probe.run_checks({"csp": probe.check_markup_sandbox_csp}).results[0]
    assert "never appeared" in never.detail

    headers = {"content-security-policy": "default-src 'self'"}  # present, but not sandbox
    responder(monkeypatch, Fetched(status=200, headers=headers, body=b"x"))
    wrong = probe.run_checks({"csp": probe.check_markup_sandbox_csp}).results[0]
    assert wrong.state == "fail"
    assert "never appeared" not in wrong.detail
    assert "not the sandbox policy" in wrong.detail


def test_the_rate_limit_check_does_not_settle() -> None:
    """It must observe a 429 on one unretried request; settling would hide it."""
    source = textwrap.dedent(inspect.getsource(probe.check_rate_limit_blocks_a_burst))
    calls = [
        node.func.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "settle" not in calls, "the rate-limit check must not wait for a 429 to appear"


# --- no check may merely report ---------------------------------------------


def test_no_check_passes_on_an_uncacheable_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """DYNAMIC means nothing was cached, and a check that names the cache must fail on it.

    `404-caching` was in this sweep until ADR-026 made uncached 404s the accepted state;
    it now asserts the opposite and is covered by its own pair of tests above.
    """
    dynamic = {**OK_HEADERS, "cf-cache-status": "DYNAMIC"}

    def answer(path: str, **_: Any) -> Fetched:
        status = 404 if "definitely-not-here" in path else 200
        return Fetched(status=status, headers=dict(dynamic), body=path.encode())

    responder(monkeypatch, answer)
    for name in ("cors-warm-cache",):
        report = probe.run_checks({name: probe.SITE_CHECKS[name]})
        assert report.results[0].state == "fail", f"{name} passed on cf-cache-status DYNAMIC"


def test_the_404_check_passes_when_no_age_is_ever_observed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absence of a non-zero Age across every sample is the documented behaviour."""
    responder(monkeypatch, Fetched(status=404, headers={"age": "0"}, body=b""))
    assert "not served from cache" in probe.check_404_caching_is_still_absent()


def test_the_404_check_fires_on_a_non_zero_age(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-zero Age is proof the 404 came from a populated entry — a real change.

    `cf-cache-status: HIT` is not, and was what made run 6's reading inconclusive.
    """
    calls = {"n": 0}

    def answer(_path: str, **_kwargs: Any) -> Fetched:
        calls["n"] += 1
        return Fetched(status=404, headers={"age": "5" if calls["n"] > 1 else "0"}, body=b"")

    responder(monkeypatch, answer)
    with pytest.raises(CheckFailed) as failure:
        probe.check_404_caching_is_still_absent()
    message = str(failure.value)
    assert "served from cache" in message
    assert "ADR-026's conclusion does not depend on the premise" in message


def test_the_404_check_carries_its_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whether it passes or fails, the reading goes in the detail."""
    responder(monkeypatch, Fetched(status=404, headers={"age": "0"}, body=b""))
    detail = probe.check_404_caching_is_still_absent()
    assert "samples" in detail


# --- cf-cache-status is retired as an instrument -----------------------------


def cache_status_reads(function: object) -> list[str]:
    """Calls to `.header("cf-cache-status")` inside a function's own body."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "header"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "cf-cache-status"
    ]


def test_no_check_reads_cf_cache_status() -> None:
    """The instrument is unavailable to checks, not merely discouraged.

    Edge nodes within a colo do not share a local cache, so a MISS means only that *this*
    node had not seen the object. It flipped a passing check to failing three times
    across runs 3-6 with nothing changed in between, and it was retired from one check
    while three others kept using it — including `cors-warm-cache`, which asserted
    `HIT` while its name promised something the status could not establish.

    `served_from_cache()` is the sanctioned way to ask, and it uses `Age`, where a
    non-zero value can only come from an entry an earlier request populated.
    """
    offenders = {
        name: reads
        for name, function in {**probe.SITE_CHECKS, **probe.BUCKET_CHECKS}.items()
        if (reads := cache_status_reads(function))
    }
    assert not offenders, (
        "these checks read cf-cache-status directly; use served_from_cache() instead:\n  "
        + "\n  ".join(f"{name}: {reads}" for name, reads in offenders.items())
    )


def test_the_ban_would_catch_a_reintroduction() -> None:
    """Negative control (AGENTS.md): a guard nobody has seen fail proves nothing."""

    def offending() -> bool:
        response = probe.fetch("/x")
        return response.header("cf-cache-status") == "HIT"

    assert cache_status_reads(offending), "the ban would not notice a new use"

    def acceptable() -> bool:
        cached, _evidence = probe.served_from_cache("/x")
        return cached

    assert not cache_status_reads(acceptable)


def test_reporting_the_distribution_is_still_allowed() -> None:
    """`_sustained` records the cache mix for evidence. Reporting is not asserting."""
    assert cache_status_reads(probe._sustained), (
        "the ban is on checks drawing verdicts from it, not on recording what was seen"
    )


def test_served_from_cache_proves_with_age_and_reports_what_it_saw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def answer(_path: str, **_kwargs: Any) -> Fetched:
        calls["n"] += 1
        age = "4" if calls["n"] > 2 else "0"
        return Fetched(status=200, headers={"age": age}, body=b"x")

    responder(monkeypatch, answer)
    cached, evidence = probe.served_from_cache("/x")
    assert cached
    assert "Age 4s" in evidence


def test_served_from_cache_is_negative_without_a_non_zero_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absence is evidence, not proof — and the message has to say how hard it looked."""
    responder(monkeypatch, Fetched(status=200, headers={"age": "0"}, body=b"x"))
    cached, evidence = probe.served_from_cache("/x", samples=3)
    assert not cached
    assert "3 samples" in evidence


def test_the_rate_is_held_constant_across_runs() -> None:
    """Consistency at a rate is the question; a varying rate answers a different one."""
    source = textwrap.dedent(inspect.getsource(probe._sustained))
    assert "RATE_LIMIT_TARGET_RPS" in source
    assert probe.RATE_LIMIT_TARGET_RPS == 262, "the rate that fired in run 6"
    assert probe.RATE_LIMIT_TARGET_RPS > probe.RATE_LIMIT_REQUESTS / probe.RATE_LIMIT_PERIOD_SECONDS


def test_a_rate_outside_the_band_is_a_precondition_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A different rate is a different experiment, not a result about the rule.

    The cross-run comparison is about consistency at 262/s; a run that managed 60/s
    answers a question nobody asked.
    """
    one_identity(monkeypatch)
    monkeypatch.setattr(probe.time, "monotonic", REAL_MONOTONIC)
    monkeypatch.setattr(probe, "RATE_LIMIT_SUSTAIN_SECONDS", 0.05)
    monkeypatch.setattr(probe, "RATE_LIMIT_WORKERS", 1)
    monkeypatch.setattr(probe, "RATE_LIMIT_TARGET_RPS", 100_000)
    responder(monkeypatch, everything_ok)

    report = probe.run_checks({"rate-limit": probe.check_rate_limit_blocks_a_burst})
    detail = report.results[0].detail
    assert "precondition unmet" in detail
    assert "different experiment" in detail
