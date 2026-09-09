"""M4.3: the live contract checks, and the retry that must not reach the probe.

`verify-live` and `probe` sit on opposite sides of the same header. The probe *provokes*
the rate limit and treats a 429 as its result; `verify-live` is checking published bytes
and a 429 is noise on the way there, so it retries after 10 s. Separate modules with
separate fetchers on purpose — a shared one with a flag would be one wrong argument away
from a probe that cannot see the thing it exists to see.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import textwrap
from typing import Any

import pytest

from loremfile.infra import probe, purge, verify_live
from loremfile.infra.verify_live import Response, Status

MIME = "application/pdf"


def entry(path: str = "pdf/a4-3pages.pdf", body: bytes = b"%PDF-1.7") -> dict[str, Any]:
    return {
        "path": path,
        "bytes": len(body),
        "mime": MIME,
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def good_headers(length: int, mime: str = MIME) -> dict[str, str]:
    return {
        "content-type": mime,
        "content-length": str(length),
        "cache-control": "public, max-age=31536000, immutable",
        "accept-ranges": "bytes",
        "x-content-type-options": "nosniff",
        "cross-origin-resource-policy": "cross-origin",
        "x-robots-tag": "noindex",
    }


# --- the two fetchers must stay apart ---------------------------------------


def test_verify_live_retries_a_429_and_the_probe_does_not() -> None:
    """The documented difference between the two tools, asserted on both at once.

    docs/12 §4 says verify-live retries our own rate limit; `probe.fetch` must not, or
    the rate-limit check can never observe a 429. If these ever share an implementation,
    this test is what notices.
    """
    live = textwrap.dedent(inspect.getsource(verify_live.fetch))
    assert "MAX_RATE_LIMIT_RETRIES" in live
    assert [n for n in ast.walk(ast.parse(live)) if isinstance(n, ast.For | ast.While)]

    probe_source = textwrap.dedent(inspect.getsource(probe.fetch))
    assert not [
        n for n in ast.walk(ast.parse(probe_source)) if isinstance(n, ast.For | ast.While)
    ], "probe.fetch must issue exactly one request"
    assert verify_live.fetch is not probe.fetch


def test_a_429_is_retried_then_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def once(*_a: object, **_k: object) -> Response:
        calls["n"] += 1
        return Response(status=429, headers={})

    monkeypatch.setattr(verify_live, "_once", once)
    monkeypatch.setattr(verify_live.time, "sleep", lambda _s: None)
    assert verify_live.fetch("/x").status == 429
    assert calls["n"] == verify_live.MAX_RATE_LIMIT_RETRIES


def test_a_non_429_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def once(*_a: object, **_k: object) -> Response:
        calls["n"] += 1
        return Response(status=404, headers={})

    monkeypatch.setattr(verify_live, "_once", once)
    assert verify_live.fetch("/x").status == 404
    assert calls["n"] == 1, "only our own rate limit is worth waiting for"


# --- the contract -----------------------------------------------------------


def test_a_correct_fixture_passes() -> None:
    e = entry()
    response = Response(status=200, headers=good_headers(e["bytes"]))
    assert [f.status for f in verify_live.check_fixture_headers(e, response)] == [Status.OK]


def test_each_contract_breach_gets_its_own_status() -> None:
    e = entry()
    cases = {
        Status.MISSING_OBJECT: Response(status=404, headers={}),
        Status.STATUS: Response(status=500, headers={}),
        Status.TIMEOUT: Response(status=0, headers={}),
    }
    for expected, response in cases.items():
        assert verify_live.check_fixture_headers(e, response)[0].status is expected


def test_a_length_or_type_mismatch_is_named_precisely() -> None:
    e = entry()
    wrong_length = Response(status=200, headers=good_headers(e["bytes"] + 1))
    statuses = [f.status for f in verify_live.check_fixture_headers(e, wrong_length)]
    assert Status.CONTENT_LENGTH_MISMATCH in statuses

    wrong_type = Response(status=200, headers=good_headers(e["bytes"], mime="text/plain"))
    statuses = [f.status for f in verify_live.check_fixture_headers(e, wrong_type)]
    assert Status.CONTENT_TYPE_MISMATCH in statuses


def test_a_missing_header_is_reported_by_name() -> None:
    e = entry()
    headers = good_headers(e["bytes"])
    del headers["x-robots-tag"]
    findings = verify_live.check_fixture_headers(e, Response(status=200, headers=headers))
    assert findings[0].status is Status.HEADER_MISSING
    assert "x-robots-tag" in findings[0].detail


def test_markup_needs_the_sandbox_csp_and_a_pdf_must_not_have_one() -> None:
    """The asymmetry matters: a CSP on a PDF breaks viewers and passes every other check."""
    markup = entry("html/basic.html", b"<!doctype html>")
    without = Response(status=200, headers=good_headers(markup["bytes"], "text/html"))
    assert any(
        "sandbox CSP" in f.detail for f in verify_live.check_fixture_headers(markup, without)
    )

    document = entry()
    headers = good_headers(document["bytes"])
    headers["content-security-policy"] = "sandbox; default-src 'none'"
    findings = verify_live.check_fixture_headers(document, Response(status=200, headers=headers))
    assert any("unexpected CSP" in f.detail for f in findings)


def test_the_hash_check_is_the_one_that_matters() -> None:
    e = entry()
    right = Response(status=200, headers={}, body=b"%PDF-1.7")
    assert verify_live.check_fixture_bytes(e, right).status is Status.OK

    wrong = Response(status=200, headers={}, body=b"%PDF-1.7 tampered")
    finding = verify_live.check_fixture_bytes(e, wrong)
    assert finding.status is Status.HASH_MISMATCH
    assert "manifest" in finding.detail


def test_smoke_picks_the_smallest_fixture_per_format_deterministically() -> None:
    entries = [
        {"path": "pdf/big.pdf", "bytes": 100},
        {"path": "pdf/small.pdf", "bytes": 10},
        {"path": "pdf/tie.pdf", "bytes": 10},
        {"path": "png/only.png", "bytes": 50},
    ]
    chosen = [e["path"] for e in verify_live.smallest_per_format(entries)]
    assert chosen == ["pdf/small.pdf", "png/only.png"], "ties broken by path order"


# --- purge ------------------------------------------------------------------


def test_purge_never_targets_a_fixture_prefix() -> None:
    """Immutable bytes: purging one can only discard a still-correct entry and cost a read."""
    prefixes, files = purge.site_targets(["pdf", "png"])
    for target in [*prefixes, *files]:
        assert "/pdf/a4" not in target
    assert all(not p.endswith("/pdf/") for p in prefixes)


def test_purge_covers_both_forms_of_a_format_page() -> None:
    """ADR-006 stores `/pdf` and `/pdf/index.html`; a stale copy of either is a stale page."""
    _prefixes, files = purge.site_targets(["pdf"])
    assert "https://loremfile.dev/pdf" in files
    assert "https://loremfile.dev/pdf/" in files
    assert "https://loremfile.dev/pdf/index.json" in files


def test_purge_batches_at_the_free_plan_limit() -> None:
    assert purge.BATCH == 100
    assert len(purge._batched(list(range(250)))) == 3  # type: ignore[arg-type]
