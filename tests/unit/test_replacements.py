"""/replacements: sample-file URLs that fail for a plain client, and the command that re-reads them.

No test here touches the network: `observe` takes its opener as a parameter and the command is run
with the reading replaced. Each classification has a control showing the neighbour it must not be
mistaken for, and the page is held to what the data says and to what the site never does, which
is to link to somebody else's host.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from loremfile import config
from loremfile import replacements as module
from loremfile.cli import main
from loremfile.manifest import is_alias
from loremfile.replacements import Observation, Reading, classify, matches
from loremfile.site import build

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "site" / "content" / "replacements.yaml"
WHEN = dt.datetime(2026, 9, 15, 12, 0, tzinfo=dt.UTC)
CHECKED, ROWS = module.load(DATA)
MANIFEST = {e["path"]: e for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
HOSTS = {
    "commondatastorage.googleapis.com",
    "africau.edu",
    "sample-videos.com",
    "file-examples.com",
    "www.soundhelix.com",
}


# --- the data ---------------------------------------------------------------------------------


def test_the_list_is_the_five_that_were_read_and_not_the_one_that_was_not() -> None:
    """Empty-set control: everything below holds of a list with nothing in it."""
    assert {re.match(r"https://([^/]+)/", row["url"]).group(1) for row in ROWS} == HOSTS
    assert dt.date.fromisoformat(CHECKED) == dt.date(2026, 11, 13)
    assert {row["kind"] for row in ROWS} == {"status", "tls", "not-the-file", "no-cors"}
    # w3.org's dummy.pdf answers a curl that claims to be Chrome with a challenge, but a real
    # headless Chrome fetch gets the PDF (read 2026-11-13), so it fails for no plain client.
    assert not [row for row in ROWS if "w3.org" in row["url"]]


def test_every_row_names_a_published_alias_as_its_nearest_file() -> None:
    for row in ROWS:
        near = MANIFEST[row["nearest"]]
        assert is_alias(near) and near["path"].endswith(f"/sample.{near['format']}"), row
        assert row["seen"] and row["url"].startswith("https://")
    assert {row["nearest"] for row in ROWS} == {
        "mp4/sample.mp4",
        "pdf/sample.pdf",
        "mp3/sample.mp3",
    }


def test_a_row_with_an_unknown_kind_or_a_plain_http_url_is_refused(tmp_path: Path) -> None:
    def written(row: dict[str, Any]) -> Path:
        path = tmp_path / f"{abs(hash(json.dumps(row)))}.yaml"
        path.write_text(yaml.safe_dump({"checked": "2026-11-13", "entries": [row]}))
        return path

    good = {"url": "https://example.org/a.pdf", "kind": "status", "status": 404, "seen": "x"}
    assert module.load(written(good))[1] == [good]
    with pytest.raises(ValueError, match="kind must be one of"):
        module.load(written({**good, "kind": "slow"}))
    with pytest.raises(ValueError, match="https URL"):
        module.load(written({**good, "url": "http://example.org/a.pdf"}))
    empty = tmp_path / "empty.yaml"
    empty.write_text("checked: 2026-11-13\nentries: []\n")
    with pytest.raises(ValueError, match="at least one entry"):
        module.load(empty)


# --- naming what a plain client saw ----------------------------------------------------------


def test_classify_names_each_kind_and_not_its_neighbour() -> None:
    pdf, mp3 = "https://example.org/a.pdf", "https://example.org/a.mp3"
    assert classify(pdf, Observation(status=403)) == Reading(pdf, "status", 403, "403")
    assert classify(pdf, Observation(status=404)).status == 404
    assert classify(pdf, Observation(error="tls")).kind == "tls"
    assert classify(pdf, Observation(status=200, content_type="text/html; charset=UTF-8")).kind == (
        "not-the-file"
    )
    # Controls: HTML at an .html URL is the file; a PDF at a .pdf URL is, whatever the casing.
    assert (
        classify("https://example.org/a.html", Observation(200, "text/html", "*")).kind == "works"
    )
    assert classify(pdf, Observation(200, "Application/PDF", "*")).kind == "works"
    assert classify(mp3, Observation(status=200, content_type="audio/mpeg")).kind == "no-cors"
    assert classify(mp3, Observation(200, "audio/mpeg", "*")).kind == "works"
    assert classify(mp3, Observation(error="network: timed out")).kind == "unreadable"
    assert classify(mp3, Observation()).kind == "unreadable"


def test_a_row_holds_only_for_the_same_kind_and_the_same_status() -> None:
    row = {"url": "https://example.org/a.pdf", "kind": "status", "status": 403}
    assert matches(row, Reading(row["url"], "status", 403, "403"))
    assert not matches(row, Reading(row["url"], "status", 404, "404")), "a different status"
    assert not matches(row, Reading(row["url"], "works", 200, "200")), "it works again"
    assert not matches(row, Reading(row["url"], "unreadable", None, "timed out"))
    tls = {"url": "https://example.org/a.pdf", "kind": "tls"}
    assert matches(tls, Reading(tls["url"], "tls", None, "x"))


# --- reading it ------------------------------------------------------------------------------


class Response:
    def __init__(self, status: int, headers: dict[str, str]) -> None:
        self.status, self.headers = status, headers

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _count: int) -> bytes:
        return b"<html>"


def test_observe_sends_our_agent_and_a_foreign_origin_and_nothing_else() -> None:
    seen: list[Any] = []

    def opener(request: urllib.request.Request, timeout: int) -> Response:
        seen.append((request, timeout))
        return Response(200, {"Content-Type": "audio/mpeg"})

    result = module.observe("https://example.org/a.mp3", opener=opener)
    request, timeout = seen[0]
    assert result == Observation(status=200, content_type="audio/mpeg", allow_origin=None)
    assert dict(request.header_items()) == {
        "User-agent": config.VERIFY_USER_AGENT,
        "Origin": module.PROBE_ORIGIN,
    }
    assert request.get_method() == "GET" and timeout == module.TIMEOUT_S


def test_observe_reports_a_status_a_certificate_failure_and_a_network_failure() -> None:
    def refusing(_request: object, **_kw: object) -> Response:
        raise urllib.error.HTTPError(
            "u", 403, "Forbidden", {"Content-Type": "application/xml"}, None
        )

    def untrusted(_request: object, **_kw: object) -> Response:
        raise urllib.error.URLError(ssl.SSLCertVerificationError("hostname mismatch"))

    def down(_request: object, **_kw: object) -> Response:
        raise urllib.error.URLError(OSError("connection refused"))

    def slow(_request: object, **_kw: object) -> Response:
        raise TimeoutError("timed out")

    assert module.observe("https://e.org/a", opener=refusing).status == 403
    assert module.observe("https://e.org/a", opener=untrusted).error == "tls"
    assert module.observe("https://e.org/a", opener=down).error.startswith("network:")
    assert module.observe("https://e.org/a", opener=slow).error.startswith("network:")
    assert module.observe("https://e.org/a", opener=down).error != "tls", "control"


def canned(overrides: dict[str, Observation] | None = None):
    """An `observe` that returns what each row says, except where `overrides` says otherwise."""
    readings = {
        "status": lambda row: Observation(status=row["status"]),
        "tls": lambda _row: Observation(error="tls"),
        "not-the-file": lambda _row: Observation(status=200, content_type="text/html"),
        "no-cors": lambda _row: Observation(status=200, content_type="audio/mpeg"),
    }
    by_url = {row["url"]: readings[row["kind"]](row) for row in ROWS}
    by_url.update(overrides or {})
    return lambda url, **_: by_url[url]


def test_check_says_which_row_no_longer_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "observe", canned())
    assert [held for _, _, held in module.check(ROWS)] == [True] * len(ROWS)
    africau = next(r["url"] for r in ROWS if "africau" in r["url"])
    monkeypatch.setattr(
        module, "observe", canned({africau: Observation(200, "application/pdf", "*")})
    )
    held = {row["url"]: ok for row, _, ok in module.check(ROWS)}
    assert [url for url, ok in held.items() if not ok] == [africau]


def test_the_command_exits_zero_when_every_row_holds_and_one_when_one_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_network(*_a: object, **_k: object) -> None:
        raise AssertionError("a test reached the network")

    monkeypatch.setattr(urllib.request, "build_opener", no_network)
    monkeypatch.setattr(module, "observe", canned())
    ok = CliRunner().invoke(main, ["replacements", "check", "--json"])
    report = json.loads(ok.output)
    assert ok.exit_code == 0 and report["summary"] == {
        "rows": len(ROWS),
        "changed": 0,
        "listed_on": CHECKED,
    }
    sound = next(r["url"] for r in ROWS if "soundhelix" in r["url"])
    monkeypatch.setattr(module, "observe", canned({sound: Observation(200, "audio/mpeg", "*")}))
    changed = CliRunner().invoke(main, ["replacements", "check", "--json"])
    assert changed.exit_code == 1
    errors = json.loads(changed.output)["errors"]
    assert errors == [f"{sound}: listed as no-cors, now works (200, audio/mpeg, CORS open)"]


# --- the page ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("replacements") / "site"
    build.build(out, root=ROOT, committed=WHEN)
    return out


def test_the_page_lists_every_row_as_text_with_what_was_seen_and_the_nearest_file(site) -> None:
    html = (site / "replacements.html").read_text(encoding="utf-8")
    assert "Read on 13 November 2026." in html
    body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    assert len(re.findall(r"<tr>", body)) == len(ROWS) == 5
    for row in ROWS:
        assert f"<code>{row['url']}</code>" in body, row["url"]
        assert row["seen"] in body
        near = f"https://loremfile.dev/{row['nearest']}"
        assert f'<a href="/{row["nearest"]}"><code>{near}</code></a>' in body
        assert f'data-copy="{near}"' in body and f'href="/{row["nearest"]}" download' in body


def test_the_page_never_links_to_the_hosts_it_lists_and_says_where_ours_differs(site) -> None:
    html = (site / "replacements.html").read_text(encoding="utf-8")
    external = re.findall(r'(?:href|src)="(https?://[^"]+)"', html)
    assert not [url for url in external if any(host in url for host in HOSTS)], external
    seconds = MANIFEST["mp4/sample.mp4"]["props"]["duration_ms"] / 1000
    assert f"Where ours differs: a {seconds:g}-second" in html
    assert "not a film" in html


def test_the_page_is_linked_from_home_llms_and_the_sitemap_and_its_name_is_reserved(site) -> None:
    assert 'href="/replacements"' in (site / "index.html").read_text(encoding="utf-8")
    assert "https://loremfile.dev/replacements" in (site / "llms.txt").read_text(encoding="utf-8")
    assert "<loc>https://loremfile.dev/replacements</loc>" in (site / "sitemap.xml").read_text(
        encoding="utf-8"
    )
    assert "replacements" in build.RESERVED


def test_the_monthly_runbook_names_the_command() -> None:
    runbook = (ROOT / "docs" / "11-operations-runbook.md").read_text(encoding="utf-8")
    assert "loremfile replacements check" in runbook
    assert "/replacements" in (ROOT / "docs" / "07-website.md").read_text(encoding="utf-8")
