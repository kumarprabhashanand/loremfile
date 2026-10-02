"""IndexNow: what a deploy announces, to whom, and why it can never fail the deploy.

docs/04 §12. Every rule here has a control beside it: the legal pages are excluded *and* a
normal page is not, the cap replaces the list *and* 100 pages do not trip it, a refusal
leaves exit 0 *and* the status is still reported.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from loremfile import cli, config
from loremfile.infra import indexnow, upload
from loremfile.site import checks, routes

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"
HOME = "https://loremfile.dev/"
SITEMAP = "https://loremfile.dev/sitemap.xml"


def report(keys: list[str], *, dry_run: bool = False, written: int | None = None) -> dict:
    """An `upload --site --json` report, in the shape `_publish_site` emits."""
    return {
        "command": "upload",
        "ok": True,
        "summary": {
            "mode": "site",
            "uploaded": len(keys),
            "written": len(keys) if written is None else written,
            "dry_run": dry_run,
        },
        "items": [{"path": key, "status": "upload", "detail": ""} for key in keys],
        "errors": [],
    }


# --- what is announced -------------------------------------------------------------------


def test_the_payload_names_this_host_and_its_key_file() -> None:
    body = indexnow.payload([HOME])
    assert body == {
        "host": "loremfile.dev",
        "key": config.INDEXNOW_KEY,
        "keyLocation": f"https://loremfile.dev/{config.INDEXNOW_KEY}.txt",
        "urlList": [HOME],
    }


def test_changed_pages_become_absolute_urls_on_this_host() -> None:
    pages = indexnow.changed_pages(["index.html", "docs/getting-started", "pdf"])
    assert pages == [
        "https://loremfile.dev/docs/getting-started",
        HOME,
        "https://loremfile.dev/pdf",
    ]
    assert all(url.startswith(HOME) for url in pages)


def test_the_legal_pages_are_never_announced() -> None:
    """ADR-028: kept out of every index; announcing them would contradict the noindex header
    and the WAF rule. The control is the page beside them, which is announced."""
    uploaded = [*routes.LEGAL_KEYS, *routes.LEGAL_TWINS, "docs/faq"]
    pages = indexnow.changed_pages(uploaded)
    assert pages == ["https://loremfile.dev/docs/faq"]
    assert not any("/legal/" in url for url in pages)


def test_the_last_filter_drops_any_legal_url_whatever_built_the_list() -> None:
    """The second layer, driven directly: the first would hide it in any end-to-end test."""
    urls = [
        "https://loremfile.dev/legal/imprint",
        "https://loremfile.dev/legal/privacy/",
        "https://loremfile.dev/docs/faq",
    ]
    assert indexnow.never_legal(urls) == ["https://loremfile.dev/docs/faq"]


def test_announce_sends_no_legal_url() -> None:
    post, sent = posting(200)
    indexnow.announce([*routes.LEGAL_KEYS, "docs/faq"], post=post)
    assert sent[0]["urlList"] == ["https://loremfile.dev/docs/faq"]


def test_files_are_never_announced() -> None:
    """Fixtures, data files, the sitemap and the key file itself are files, not pages."""
    files = [
        "pdf/minimal.pdf",
        "manifest.json",
        "sitemap.xml",
        "robots.txt",
        "_formats/pdf.json",
        routes.INDEXNOW_KEY_FILE,
        routes.API_CATALOG_KEY,
    ]
    assert indexnow.changed_pages([*files, "formats"]) == ["https://loremfile.dev/formats"]


def test_up_to_the_cap_every_page_is_sent() -> None:
    pages = [f"https://loremfile.dev/p{i}" for i in range(indexnow.MAX_URLS)]
    assert indexnow.url_list(pages) == pages


def test_over_the_cap_the_home_page_and_the_sitemap_are_sent_instead() -> None:
    pages = [f"https://loremfile.dev/p{i}" for i in range(indexnow.MAX_URLS + 1)]
    assert indexnow.url_list(pages) == [HOME, SITEMAP]


# --- what comes back, and why it never fails the deploy -----------------------------------


def posting(status: int | Exception) -> tuple[Any, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def post(url: str, body: bytes) -> int:
        sent.append({"url": url, **json.loads(body)})
        if isinstance(status, Exception):
            raise status
        return status

    return post, sent


@pytest.mark.parametrize("status", [200, 202])
def test_200_and_202_both_mean_accepted(status: int) -> None:
    post, sent = posting(status)
    outcome = indexnow.announce(["docs/faq"], post=post)
    assert outcome.accepted
    assert f"HTTP {status}, accepted" in outcome.detail
    assert sent[0]["url"] == "https://api.indexnow.org/indexnow"


@pytest.mark.parametrize("status", [400, 403, 422, 429, 500])
def test_a_refusal_is_reported_not_raised(status: int) -> None:
    post, _ = posting(status)
    outcome = indexnow.announce(["docs/faq"], post=post)
    assert not outcome.accepted
    assert f"HTTP {status}, refused" in outcome.detail


def test_a_network_failure_is_reported_not_raised() -> None:
    post, _ = posting(OSError("connection reset"))
    outcome = indexnow.announce(["docs/faq"], post=post)
    assert outcome.status is None
    assert "not sent: connection reset" in outcome.detail


def test_nothing_changed_sends_nothing() -> None:
    post, sent = posting(200)
    outcome = indexnow.announce(["sitemap.xml", "manifest.json"], post=post)
    assert sent == []
    assert "nothing to announce" in outcome.detail


def run_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: Any, body: Any) -> Any:
    post, sent = posting(status)
    monkeypatch.setattr(indexnow, "_post", post)
    path = tmp_path / "site-upload.json"
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    result = CliRunner().invoke(cli.main, ["indexnow", "--changed-from", str(path), "--json"])
    return result, sent


@pytest.mark.parametrize("status", [403, 500, OSError("unreachable")])
def test_the_command_exits_0_on_a_refusal_and_logs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: Any
) -> None:
    result, sent = run_command(tmp_path, monkeypatch, status, report(["docs/faq"]))
    assert result.exit_code == 0, result.output
    assert len(sent) == 1, "control: the request was made"
    expected = "not sent" if isinstance(status, Exception) else f"HTTP {status}"
    assert expected in result.stderr


@pytest.mark.parametrize(
    "body",
    [
        "{ not json",
        "[]",
        # an item the upload marks written but which names no key: reached, then KeyError
        json.dumps({"ok": True, "summary": {"mode": "site"}, "items": [{"status": "upload"}]}),
    ],
)
def test_the_command_exits_0_on_any_report_it_cannot_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    result, sent = run_command(tmp_path, monkeypatch, 200, body)
    assert result.exit_code == 0, result.output
    assert sent == []


def test_the_command_exits_0_on_an_unreadable_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, sent = run_command(tmp_path, monkeypatch, 200, "{ not json")
    assert result.exit_code == 0
    assert sent == []
    assert "no readable upload report" in result.stderr


def test_the_command_announces_what_the_upload_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, sent = run_command(tmp_path, monkeypatch, 202, report(["docs/faq", "llms.txt"]))
    assert result.exit_code == 0
    assert sent[0]["urlList"] == ["https://loremfile.dev/docs/faq"]
    assert json.loads(result.stdout)["summary"] == {
        "submitted": 1,
        "status": 202,
        "accepted": True,
    }


# --- reading the upload's report ---------------------------------------------------------


def test_a_dry_run_announces_nothing() -> None:
    assert indexnow.uploaded_keys(report(["docs/faq"], dry_run=True)) == []
    assert indexnow.uploaded_keys(report(["docs/faq"])) == ["docs/faq"], "control"


def test_a_partial_upload_announces_nothing() -> None:
    """Which keys landed is not known, so none is claimed."""
    assert indexnow.uploaded_keys(report(["docs/faq", "docs/naming"], written=1)) == []


def test_a_failed_upload_announces_nothing() -> None:
    failed = {**report(["docs/faq"]), "ok": False}
    assert indexnow.uploaded_keys(failed) == []


def test_the_report_shape_is_the_one_the_upload_emits() -> None:
    """The keys read here are the ones `_publish_site` writes; a rename there would leave this
    reading nothing, every deploy, in silence."""
    source = (ROOT / "src" / "loremfile" / "cli.py").read_text(encoding="utf-8")
    publish = source[source.index("def _publish_site") : source.index('@main.command("upload")')]
    for key in ('"mode": "site"', '"written": written', '"dry_run": dry_run'):
        assert key in publish, key
    assert '{"path": step.key, "status": step.action.value' in publish


# --- the deploy --------------------------------------------------------------------------


def deploy_steps() -> list[dict[str, Any]]:
    document = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    return [step for job in document["jobs"].values() for step in job.get("steps") or []]


def test_the_upload_writes_the_report_the_indexnow_step_reads() -> None:
    [publish] = [s for s in deploy_steps() if s.get("name") == "Publish the site"]
    assert re.search(r"loremfile upload --site --json\b", publish["run"])
    assert "> build/site-upload.json" in publish["run"]
    [announce] = [s for s in deploy_steps() if "loremfile indexnow" in str(s.get("run"))]
    assert "--changed-from build/site-upload.json" in announce["run"]


def test_the_indexnow_step_comes_after_verify_live_and_cannot_fail_the_deploy() -> None:
    steps = deploy_steps()
    names = [s.get("name") for s in steps]
    verify = names.index("Verify what was published")
    [index] = [i for i, s in enumerate(steps) if "loremfile indexnow" in str(s.get("run"))]
    announce = steps[index]
    assert index > verify, "announced before verify-live had seen the pages served"
    assert announce["continue-on-error"] is True
    assert announce["if"] == "env.MODE == 'deploy'"
    for escape in ("always()", "!cancelled()", "failure()"):
        assert escape not in announce["if"], "it would run after a failed verify-live"


def test_no_workflow_treats_the_key_as_a_secret() -> None:
    """Public by design: a secret would keep the key file out of the build."""
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        assert "INDEXNOW" not in workflow.read_text(encoding="utf-8"), workflow.name


# --- the key file ------------------------------------------------------------------------


def test_the_key_is_32_hex_characters() -> None:
    assert re.fullmatch(r"[0-9a-f]{32}", config.INDEXNOW_KEY)
    assert checks.INDEXNOW_KEY_SHAPE.fullmatch(config.INDEXNOW_KEY)


def test_the_key_file_check_fires_on_each_way_to_be_wrong() -> None:
    sitemap = f"<urlset><url><loc>{HOME}</loc></url></urlset>"
    name = routes.INDEXNOW_KEY_FILE
    keys = {name, "sitemap.xml"}
    assert checks._indexnow_problems(config.INDEXNOW_KEY, sitemap, keys) == []
    assert "missing" in checks._indexnow_problems("", sitemap, {"sitemap.xml"})[0]
    assert (
        "exactly the key" in checks._indexnow_problems(config.INDEXNOW_KEY + "\n", sitemap, keys)[0]
    )
    listed = sitemap.replace("</urlset>", f"<url><loc>{HOME}{name}</loc></url></urlset>")
    assert "not a page" in checks._indexnow_problems(config.INDEXNOW_KEY, listed, keys)[0]


def test_the_removal_pass_never_deletes_the_key_file() -> None:
    """It removes tombstoned manifest entries and nothing else; the key file is never one.
    The control: a tombstoned entry beside it is removed."""
    live = {routes.INDEXNOW_KEY_FILE: "a" * 64, "pdf/gone.pdf": "b" * 64}
    entries = [{"path": "pdf/gone.pdf", "status": "removed", "reason": "takedown"}]
    plan = upload.plan_removals(entries, live)
    removed = [step.key for step in plan.by_action(upload.Action.REMOVE)]
    assert removed == ["pdf/gone.pdf"]
    assert routes.INDEXNOW_KEY_FILE not in removed


# --- the real transport, against a loopback server ----------------------------------------


@pytest.fixture
def endpoint() -> Any:
    """An IndexNow stand-in on 127.0.0.1: records each request, answers with `status`."""
    import http.server  # noqa: PLC0415
    import threading  # noqa: PLC0415

    state: dict[str, Any] = {"status": 202, "requests": []}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # http.server's spelling
            length = int(self.headers["Content-Length"])
            state["requests"].append(
                {"type": self.headers["Content-Type"], "body": self.rfile.read(length)}
            )
            self.send_response(state["status"])
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}/indexnow"
    yield state
    server.shutdown()


@pytest.mark.parametrize("status", [200, 202, 403, 422])
def test_the_transport_sends_json_and_returns_the_status(endpoint: Any, status: int) -> None:
    """The one function the tests above replace, run for real: a 4xx is a status to return,
    not an exception to raise (urllib raises HTTPError for it)."""
    endpoint["status"] = status
    body = json.dumps(indexnow.payload([HOME])).encode()
    assert indexnow._post(endpoint["url"], body) == status
    [request] = endpoint["requests"]
    assert request["type"] == "application/json; charset=utf-8"
    assert json.loads(request["body"])["keyLocation"].endswith(f"{config.INDEXNOW_KEY}.txt")


def test_an_unreachable_endpoint_is_an_outcome_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indexnow, "ENDPOINT", "http://127.0.0.1:1/indexnow")
    outcome = indexnow.announce(["docs/faq"])
    assert outcome.status is None
    assert outcome.detail.startswith("not sent:")
