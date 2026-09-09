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
EDGE_CHECKS = sorted(set(probe.SITE_CHECKS) - {"www-redirect", "404-caching", "rate-limit"})


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


def test_the_rate_limit_check_asserts_the_429(monkeypatch: pytest.MonkeyPatch) -> None:
    """Its absence is the failure. The probe must not treat a 429 as retry-and-continue."""
    responder(monkeypatch, everything_ok)
    # A clock fast enough that the load precondition is satisfied, so the check reaches
    # the assertion under test rather than stopping short of it.
    monkeypatch.setattr(probe.time, "monotonic", iter([0.0, 1.0]).__next__)
    with pytest.raises(CheckFailed, match="no 429"):
        probe.check_rate_limit_blocks_a_burst()


def test_the_rate_limit_check_passes_when_the_limit_fires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def answer(path: str, **_: Any) -> Fetched:
        if "recovered" in path:
            return Fetched(status=200, headers={}, body=b"")
        status = 429 if len(seen) > probe.RATE_LIMIT_REQUESTS else 200
        return Fetched(status=status, headers={}, body=b"")

    responder(monkeypatch, answer, record=seen)
    monkeypatch.setattr(probe.time, "monotonic", iter([0.0, 1.0]).__next__)
    assert "429 at request" in probe.check_rate_limit_blocks_a_burst()


def test_a_burst_that_never_succeeds_is_a_precondition_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-429 could be an outage rather than our rule; that is not a passing result."""
    responder(monkeypatch, Fetched(status=429, headers={}, body=b""))
    with pytest.raises(PreconditionUnmet):
        probe.check_rate_limit_blocks_a_burst()


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


def test_query_string_check_separates_an_unpropagated_rule_from_a_wrong_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two findings look identical without the settle, and need different responses.

    A MISS on the plain path means the cache rule is not live yet. A HIT on the plain
    path and a MISS with a query string means the rule *is* live and the query string is
    part of the key — which is the ADR-013 failure worth reporting.
    """
    responder(monkeypatch, Fetched(status=200, headers={"cf-cache-status": "MISS"}, body=b"x"))
    with pytest.raises(PreconditionUnmet, match="never appeared"):
        probe.check_query_strings_share_one_cache_entry()

    def by_query(path: str, **_: Any) -> Fetched:
        status = "MISS" if "?" in path else "HIT"
        return Fetched(status=200, headers={"cf-cache-status": status}, body=b"x")

    responder(monkeypatch, by_query)
    with pytest.raises(CheckFailed, match="not ignoring the query string"):
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
    """DYNAMIC means nothing was cached. Every cache-related check must fail on it.

    A sweep rather than one test each: `404-caching` reported `DYNAMIC` and passed, and
    `cors-warm-cache` named the cache in its title without asserting it. Both were the
    same shape, so the guard is written to catch the shape.
    """
    dynamic = {**OK_HEADERS, "cf-cache-status": "DYNAMIC"}

    def answer(path: str, **_: Any) -> Fetched:
        status = 404 if "definitely-not-here" in path else 200
        return Fetched(status=status, headers=dict(dynamic), body=path.encode())

    responder(monkeypatch, answer)
    for name in ("404-caching", "cors-warm-cache", "query-string-cache-key"):
        report = probe.run_checks({name: probe.SITE_CHECKS[name]})
        assert report.results[0].state == "fail", f"{name} passed on cf-cache-status DYNAMIC"


def test_the_404_check_fails_when_it_is_cacheable_but_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MISS twice means the 404 is eligible but is not actually being served from cache."""
    monkeypatch.setattr(probe.time, "sleep", lambda _s: None)
    responder(monkeypatch, Fetched(status=404, headers={"cf-cache-status": "MISS"}, body=b""))
    with pytest.raises(CheckFailed, match="not HIT"):
        probe.check_404_is_cached()


def test_the_404_check_passes_only_on_a_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    responder(monkeypatch, Fetched(status=404, headers={"cf-cache-status": "HIT"}, body=b""))
    assert "served from cache" in probe.check_404_is_cached()


def test_every_check_asserts_something() -> None:
    """A check whose body never calls `check` can only report, never fail.

    This is the shape 404-caching had: it observed, formatted a detail string, and
    returned. Nothing in the framework would have noticed.
    """
    for name, function in {**probe.SITE_CHECKS, **probe.BUCKET_CHECKS}.items():
        source = textwrap.dedent(inspect.getsource(function))
        calls = {
            node.func.id
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "check" in calls, (
            f"{name} never calls check(): it can report a problem but not fail on one"
        )


def test_url_normalization_check_is_not_a_tautology(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two absent CSPs compare equal. Found by auditing all twelve checks, not by a run.

    With no header rule at all, both paths return "" and an equality check passes while
    proving nothing — the same shape as 404-caching passing on DYNAMIC. The header must
    be required to exist before the two are compared.
    """
    responder(monkeypatch, Fetched(status=200, headers={}, body=b"x"))
    with pytest.raises(PreconditionUnmet, match="compare two absent headers"):
        probe.check_url_normalization_is_on()


def test_preflight_rejects_a_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    """A browser does not follow a redirected preflight, so neither may this check."""
    responder(monkeypatch, Fetched(status=301, headers={"location": "/"}, body=b""))
    with pytest.raises(PreconditionUnmet, match="redirected"):
        probe.check_cors_preflight()


def test_fetch_does_not_follow_redirects() -> None:
    """The www check asserts a 301; following it landed on the apex root's honest 404.

    `urlopen` follows by default, which made a working redirect look like a broken one.
    """
    assert any(isinstance(handler, probe._NoRedirects) for handler in probe._OPENER.handlers), (
        "probe.fetch must see redirects, not follow them"
    )


def test_the_rate_limit_burst_is_concurrent() -> None:
    """Sequential requests reach 12-20/s and cannot cross a 30/s threshold at all.

    The first version drew a conclusion about the rule from load it never generated.
    """
    source = textwrap.dedent(inspect.getsource(probe.check_rate_limit_blocks_a_burst))
    assert "ThreadPoolExecutor" in source
    assert probe.RATE_LIMIT_WORKERS > 1


def test_insufficient_load_is_a_precondition_not_a_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact failure from the first live run, now unable to masquerade as a finding."""
    responder(monkeypatch, everything_ok)
    monkeypatch.setattr(probe, "RATE_LIMIT_BURST", 4)
    monkeypatch.setattr(probe.time, "monotonic", iter([0.0, 100.0]).__next__)

    report = probe.run_checks({"rate-limit": probe.check_rate_limit_blocks_a_burst})
    assert report.results[0].state == "fail"
    detail = report.results[0].detail
    assert "precondition unmet" in detail
    assert "could not provoke" in detail
    assert "not in effect" not in detail, "it must not conclude anything about the rule"
