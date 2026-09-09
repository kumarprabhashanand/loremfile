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
    with pytest.raises(CheckFailed) as unserved:
        probe.check_markup_sandbox_csp()
    assert "no Content-Security-Policy" in str(unserved.value)

    responder(monkeypatch, everything_404)
    with pytest.raises(PreconditionUnmet):
        probe.check_markup_sandbox_csp()


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
    monkeypatch.setattr(probe.time, "sleep", lambda _s: None)
    with pytest.raises(CheckFailed, match="no 429"):
        probe.check_rate_limit_blocks_a_burst()


def test_the_rate_limit_check_passes_when_the_limit_fires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def answer(path: str, **_: Any) -> Fetched:
        if "recovered" in path:
            return Fetched(status=200, headers={}, body=b"")
        status = 429 if len(seen) > 300 else 200
        return Fetched(status=status, headers={}, body=b"")

    responder(monkeypatch, answer, record=seen)
    monkeypatch.setattr(probe.time, "sleep", lambda _s: None)
    assert "429 from request" in probe.check_rate_limit_blocks_a_burst()


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


def test_query_string_check_fails_without_a_cache_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No cf-cache-status means cache behaviour was not observed at all."""
    responder(monkeypatch, Fetched(status=200, headers={}, body=b"x"))
    with pytest.raises(PreconditionUnmet, match="cf-cache-status"):
        probe.check_query_strings_share_one_cache_entry()


def test_query_string_check_fails_on_a_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    responder(monkeypatch, Fetched(status=200, headers={"cf-cache-status": "MISS"}, body=b"x"))
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
