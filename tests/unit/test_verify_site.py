"""M4.1: the defacement check and the header rules' branches on site pages (docs/09 §3.2-3.3)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from loremfile.infra import verify_live
from loremfile.infra.verify_live import Response, Status
from loremfile.site import routes

META = f'<meta name="robots" content="{routes.LEGAL_ROBOTS}">'.encode()
FILES = {
    "index.html": b"<p>home</p>",
    "pdf": b"<p>pdf</p>",
    "docs": b"<p>docs</p>",
    "legal/imprint": META + b"<p>imprint</p>",
    "legal/privacy": META + b"<p>privacy</p>",
    "_formats/pdf.json": b"{}",
    "llms.txt": b"# loremfile.dev\n",
}


class Edge:
    """Production as `fetch` sees it: the built bytes, with the headers the rules set."""

    def __init__(self) -> None:
        self.bodies = {routes.public_path(key): body for key, body in FILES.items()}
        self.bodies |= {"/pdf/": FILES["pdf"], "/docs/": FILES["docs"]}
        self.overrides: dict[str, Response] = {}
        self.calls: list[str] = []

    def __call__(self, path: str, **_: Any) -> Response:
        self.calls.append(path)
        if path in self.overrides:
            return self.overrides[path]
        if path not in self.bodies:
            return Response(status=404, headers={})
        key = routes.key_for(path)
        headers = {"content-type": routes.content_type(key)}
        if routes.is_page(key):
            headers |= verify_live.EXPECTED_PAGE_HEADERS
        else:
            headers |= {"x-robots-tag": "noindex", "cross-origin-resource-policy": "cross-origin"}
        if key in routes.LEGAL_KEYS:
            headers["x-robots-tag"] = routes.LEGAL_ROBOTS
        return Response(status=200, headers=headers, body=self.bodies[path])


@pytest.fixture
def site(tmp_path: Path) -> Path:
    for key, body in FILES.items():
        path = tmp_path / routes.disk_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return tmp_path


@pytest.fixture
def edge(monkeypatch: pytest.MonkeyPatch) -> Edge:
    fake = Edge()
    monkeypatch.setattr(verify_live, "fetch", fake)
    return fake


def failures(findings: list[verify_live.Finding]) -> list[tuple[str, Status, str]]:
    return [(f.path, f.status, f.detail) for f in findings if f.status is not Status.OK]


def test_a_site_that_matches_its_build_passes_and_every_key_was_fetched(
    site: Path, edge: Edge
) -> None:
    findings = verify_live.site_findings(site)
    assert failures(findings) == []
    assert {routes.public_path(key) for key in FILES} | {"/pdf/", "/docs/"} <= set(edge.calls)


def test_a_defaced_page_is_a_hash_mismatch(site: Path, edge: Edge) -> None:
    edge.bodies["/pdf"] = b"<p>not ours</p>"
    (found,) = [f for f in failures(verify_live.site_findings(site)) if f[0] == "/pdf"]
    assert found[1] is Status.HASH_MISMATCH


def test_a_mismatch_during_a_deploy_is_retried_once_after_the_wait(site: Path, edge: Edge) -> None:
    edge.overrides["/pdf"] = Response(status=404, headers={})
    waited: list[float] = []

    def sleep(seconds: float) -> None:
        waited.append(seconds)
        edge.overrides.clear()

    assert failures(verify_live.site_findings(site, retry_after=600, sleep=sleep)) == []
    assert waited == [600]


def test_without_a_retry_the_mismatch_stands(site: Path, edge: Edge) -> None:
    edge.overrides["/pdf"] = Response(status=404, headers={})
    assert ("/pdf", Status.MISSING_OBJECT, "404") in failures(verify_live.site_findings(site))


def test_an_empty_build_is_a_finding_not_a_clean_check(tmp_path: Path, edge: Edge) -> None:
    (found,) = verify_live.site_findings(tmp_path)
    assert found.status is Status.MISSING_OBJECT
    assert edge.calls == []


def test_a_legal_page_without_its_robots_header_or_meta_fails(site: Path, edge: Edge) -> None:
    headers = {"content-type": "text/html; charset=utf-8", **verify_live.EXPECTED_PAGE_HEADERS}
    edge.overrides["/legal/imprint"] = Response(
        status=200, headers=headers, body=FILES["legal/imprint"]
    )
    edge.overrides["/legal/privacy"] = Response(
        status=200, headers={**headers, "x-robots-tag": routes.LEGAL_ROBOTS}, body=b"<p>no meta</p>"
    )
    found = failures(verify_live.site_findings(site))
    assert any(path == "/legal/imprint" and "x-robots-tag" in detail for path, _, detail in found)
    assert any(path == "/legal/privacy" and "robots meta" in detail for path, _, detail in found)


def test_file_headers_on_a_page_mean_the_index_html_exclusion_broke(site: Path, edge: Edge) -> None:
    headers = {
        "content-type": "text/html; charset=utf-8",
        **verify_live.EXPECTED_PAGE_HEADERS,
        "cross-origin-resource-policy": "cross-origin",
    }
    edge.overrides["/"] = Response(status=200, headers=headers, body=FILES["index.html"])
    assert any(
        path == "/" and "fixture headers" in detail
        for path, _, detail in failures(verify_live.site_findings(site))
    )


def test_a_missing_slash_rewrite_is_reported(site: Path, edge: Edge) -> None:
    del edge.bodies["/pdf/"]
    assert any(
        path == "/pdf/" and "ADR-032" in detail
        for path, _, detail in failures(verify_live.site_findings(site))
    )


def test_a_format_index_must_carry_the_file_headers(site: Path, edge: Edge) -> None:
    edge.overrides["/pdf/index.json"] = Response(
        status=200,
        headers={"content-type": "application/json", "content-security-policy": routes.SITE_CSP},
        body=FILES["_formats/pdf.json"],
    )
    found = failures(verify_live.site_findings(site))
    assert ("/pdf/index.json", Status.HEADER_VALUE, "not served with the file headers") in found


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            Response(
                status=200, headers={}, body=b"Contact: x\r\nExpires: 2027-09-15T12:00:00Z\r\n"
            ),
            dt.datetime(2027, 9, 15, 12, tzinfo=dt.UTC),
        ),
        (Response(status=404, headers={}), "answered 404"),
        (Response(status=200, headers={}, body=b"Contact: x\n"), "no Expires"),
    ],
)
def test_security_txt_expiry(
    monkeypatch: pytest.MonkeyPatch, response: Response, expected: object
) -> None:
    monkeypatch.setattr(verify_live, "fetch", lambda *_a, **_k: response)
    if isinstance(expected, dt.datetime):
        assert verify_live.security_txt_expiry() == expected
    else:
        with pytest.raises(ValueError, match=str(expected)):
            verify_live.security_txt_expiry()
