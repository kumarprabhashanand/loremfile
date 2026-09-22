"""The rest of smoke: the manifest count, a CORS preflight, Range and the `www` redirect.

Each check is driven with the answer production gives today (observed 2026-09-21) and with
the answers it exists to catch — including absence, so none of them passes on nothing.
"""

from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from click.testing import CliRunner

from loremfile import cli
from loremfile.infra import verify_live
from loremfile.infra.verify_live import Response, Status


def entry(path: str, size: int) -> dict[str, Any]:
    return {"path": path, "bytes": size, "mime": "application/octet-stream", "sha256": "0" * 64}


def manifest(count: object, statuses: list[str]) -> Response:
    fixtures = [{"path": f"f/{i}", "status": s} for i, s in enumerate(statuses)]
    return Response(200, {}, json.dumps({"count": count, "fixtures": fixtures}).encode())


# --- the manifest count ---------------------------------------------------------------


def test_the_live_manifest_count_equals_this_checkout() -> None:
    finding = verify_live.check_manifest_count(2, manifest(2, ["active", "active"]))
    assert finding.status is Status.OK


@pytest.mark.parametrize(
    "response",
    [
        manifest(3, ["active", "active", "active"]),  # one more published than committed
        manifest(2, ["active", "removed"]),  # the count and its own list disagree
        manifest(None, ["active", "active"]),  # no count at all
        Response(200, {}, json.dumps({"count": 2}).encode()),  # no list to count
        Response(200, {}, b"<html>not the manifest</html>"),
        Response(200, {}, b""),
    ],
)
def test_a_manifest_that_differs_or_cannot_be_counted_fails(response: Response) -> None:
    assert verify_live.check_manifest_count(2, response).status is Status.COUNT_MISMATCH


def test_an_unreachable_manifest_fails_on_its_status() -> None:
    finding = verify_live.check_manifest_count(2, Response(404, {}))
    assert (finding.status, finding.detail) == (Status.STATUS, "404")


# --- Range ------------------------------------------------------------------------------

SMALL, LARGE = entry("edge/small.xml", 122), entry("bin/large.bin", 100_000_000)


def ranged(size: int, *, status: int = 206, body: bytes = b"x" * 100) -> Response:
    return Response(status, {"content-range": f"bytes 0-99/{size}"}, body)


def test_a_satisfied_range_passes() -> None:
    assert verify_live.check_range(LARGE, ranged(100_000_000)).status is Status.OK


@pytest.mark.parametrize(
    ("response", "status"),
    [
        (Response(200, {}, b"x" * 101), Status.STATUS),  # Range ignored: the whole object
        (ranged(99_999_999), Status.HEADER_VALUE),  # a range of some other object
        (Response(206, {}, b"x" * 100), Status.HEADER_MISSING),
        (ranged(100_000_000, body=b"x" * 99), Status.CONTENT_LENGTH_MISMATCH),
    ],
)
def test_a_range_that_is_ignored_or_wrong_fails(response: Response, status: Status) -> None:
    assert verify_live.check_range(LARGE, response).status is status


def test_the_two_range_targets_are_the_smallest_and_largest_above_the_range() -> None:
    tiny = entry("txt/empty.txt", 0)
    assert verify_live.range_targets([LARGE, tiny, SMALL]) == [SMALL, LARGE]
    assert verify_live.range_targets([tiny]) == []


# --- the preflight ----------------------------------------------------------------------

#: What production answered on 2026-09-21.
PREFLIGHT = {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, HEAD",
    "access-control-allow-headers": "range",
    "access-control-max-age": "86400",
}


def test_production_s_preflight_answer_passes() -> None:
    [finding] = verify_live.check_preflight(SMALL, Response(204, PREFLIGHT))
    assert finding.status is Status.OK


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"access-control-allow-origin": ""}, Status.HEADER_MISSING),
        ({"access-control-allow-origin": "https://loremfile.dev"}, Status.HEADER_VALUE),
        ({"access-control-allow-methods": "HEAD"}, Status.HEADER_VALUE),
        ({"access-control-allow-headers": ""}, Status.HEADER_MISSING),
    ],
)
def test_a_preflight_that_would_block_a_ranged_get_fails(
    change: dict[str, str], status: Status
) -> None:
    headers = {k: v for k, v in {**PREFLIGHT, **change}.items() if v}
    findings = verify_live.check_preflight(SMALL, Response(204, headers))
    assert [f.status for f in findings] == [status]


def test_a_preflight_refused_or_redirected_fails() -> None:
    for code in (301, 403, 404):
        [finding] = verify_live.check_preflight(SMALL, Response(code, PREFLIGHT))
        assert finding.status is Status.STATUS


# --- the www redirect -------------------------------------------------------------------

PATH = "/edge/small.xml?verify-live"


def test_a_301_to_the_same_path_and_query_on_the_apex_passes() -> None:
    response = Response(301, {"location": f"https://loremfile.dev{PATH}"})
    assert verify_live.check_www_redirect(PATH, response).status is Status.OK


@pytest.mark.parametrize(
    ("response", "status"),
    [
        (Response(200, {}), Status.STATUS),  # a followed redirect looks exactly like this
        (Response(302, {"location": f"https://loremfile.dev{PATH}"}), Status.STATUS),
        (Response(301, {"location": "https://loremfile.dev/"}), Status.HEADER_VALUE),
        (Response(301, {"location": "https://loremfile.dev/edge/small.xml"}), Status.HEADER_VALUE),
        (Response(301, {}), Status.HEADER_MISSING),
    ],
)
def test_a_redirect_that_is_missing_or_loses_the_path_fails(
    response: Response, status: Status
) -> None:
    assert verify_live.check_www_redirect(PATH, response).status is status


# --- the legal pages refuse declared AI agents ------------------------------------------


def test_a_403_to_a_declared_ai_agent_passes() -> None:
    agent = verify_live.REFUSED_AGENTS[0]
    finding = verify_live.check_agent_refused(agent, "/legal/imprint", Response(403, {}))
    assert (finding.status, finding.path) == (Status.OK, "ai-agent:CCBot /legal/imprint")


@pytest.mark.parametrize("status", [200, 404, 429, 500])
def test_anything_but_a_403_fails(status: int) -> None:
    """200 is the failure this exists for: the page naming the operator was served."""
    agent = verify_live.REFUSED_AGENTS[1]
    finding = verify_live.check_agent_refused(agent, "/legal/privacy", Response(status, {}))
    assert finding.status is Status.STATUS
    assert finding.path == "ai-agent:PerplexityBot /legal/privacy"
    assert str(status) in finding.detail


def test_the_agents_are_asked_for_both_legal_pages_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder()
    monkeypatch.setattr(verify_live, "fetch", recorder)
    verify_live.contract_findings([LARGE, SMALL])
    asked = {
        (path, (kwargs.get("extra_headers") or {}).get("User-Agent"))
        for path, kwargs in recorder.calls
        if path.startswith("/legal/")
    }
    assert asked == {
        (page, agent)
        for page in ("/legal/imprint", "/legal/privacy")
        for agent in verify_live.REFUSED_AGENTS
    }


# --- what is actually requested ---------------------------------------------------------


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, path: str, **kwargs: Any) -> Response:
        self.calls.append((path, kwargs))
        return Response(404, {})


def test_the_requests_carry_what_each_check_depends_on(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder()
    monkeypatch.setattr(verify_live, "fetch", recorder)
    verify_live.contract_findings([LARGE, SMALL])
    calls = dict(recorder.calls)
    assert set(calls) == {
        "/manifest.json",
        "/edge/small.xml",
        "/bin/large.bin",
        PATH,
        "/legal/imprint",
        "/legal/privacy",
    }
    preflight = next(k for p, k in recorder.calls if k.get("method") == "OPTIONS")
    assert preflight["extra_headers"]["Access-Control-Request-Headers"] == "range"
    ranges = [k for p, k in recorder.calls if "Range" in (k.get("extra_headers") or {})]
    assert len(ranges) == 2 and all(k["limit"] == 101 for k in ranges)
    assert calls[PATH]["host"] == "www.loremfile.dev"
    assert calls[PATH]["redirects"] is False


def test_nothing_to_request_is_a_failure_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify_live, "fetch", Recorder())
    findings = verify_live.contract_findings([entry("txt/empty.txt", 0)])
    assert [f.status for f in findings] == [Status.STATUS, Status.MISSING_OBJECT]


@pytest.mark.parametrize(
    ("args", "expected"), [(["--mode", "smoke"], True), (["--only", "x"], False)]
)
def test_every_mode_runs_them_and_only_does_not(
    monkeypatch: pytest.MonkeyPatch, args: list[str], expected: bool
) -> None:
    asked: list[bool] = []
    monkeypatch.setattr(verify_live, "contract_findings", lambda _e: asked.append(True) or [])
    monkeypatch.setattr(verify_live, "fetch", Recorder())
    CliRunner().invoke(cli.main, ["verify-live", *args, "--json"])
    assert bool(asked) is expected


# --- the opener, one level below `fetch` ------------------------------------------------


class Redirecting(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/from":
            self.send_response(301)
            self.send_header("Location", "/to")
            self.end_headers()
            return
        body = b"y" * 100
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        pass


@pytest.fixture
def server() -> Iterator[str]:
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Redirecting)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_redirects_false_returns_the_301_itself(server: str) -> None:
    kept = verify_live._open(f"{server}/from", method="GET", headers={}, redirects=False)
    assert (kept.status, kept.header("location")) == (301, "/to")
    # The control: the same request with redirects followed arrives at the target.
    followed = verify_live._open(f"{server}/from", method="GET", headers={})
    assert followed.status == 200


def test_limit_reads_no_more_than_asked(server: str) -> None:
    response = verify_live._open(f"{server}/to", method="GET", headers={}, limit=5)
    assert response.body == b"yyyyy"
    assert len(verify_live._open(f"{server}/to", method="GET", headers={}).body) == 100
