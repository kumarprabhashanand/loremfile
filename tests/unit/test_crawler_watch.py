"""The weekly crawler watch: what it reports, and what it must never do (docs/09 §3.4).

Two properties carry the weight. A run that could not read the list must leave the advisory
issue alone — reporting `ok` there would close a real advisory on a run that learned nothing
(`11` §7.2) — and the watch never edits a rule, because blocking an agent is a decision.
"""

from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml
from click.testing import CliRunner

from loremfile import cli
from loremfile.infra import crawlers

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/audit.yml").read_text(encoding="utf-8"))


def known(*names: str) -> dict[str, Any]:
    return {name: {"operator": f"{name} Inc", "function": "AI Crawler"} for name in names}


# --- what counts as decided already ------------------------------------------------------


def test_the_blocked_set_is_read_from_both_places_a_decision_is_recorded() -> None:
    """Empty-set control first: name tokens that must be found, from the rule and robots.txt."""
    blocked = crawlers.blocked_tokens(ROOT)
    assert {"gptbot", "ccbot", "bytespider", "claudebot"} <= blocked, "the WAF rule's tokens"
    assert {"google-extended", "applebot-extended"} <= blocked, "robots.txt's own tokens"
    assert "*" not in blocked
    assert all(token == token.lower() for token in blocked)


def test_the_seen_file_records_the_agents_already_weighed() -> None:
    seen = crawlers.seen_names(ROOT)
    assert len(seen) > 100, "control: the baseline is populated"
    assert "gptbot" in seen


@pytest.mark.parametrize("decided", ["Amazonbot", "amazonbot", "AMAZONBOT"])
def test_an_agent_already_blocked_is_not_reported_whatever_its_casing(decided: str) -> None:
    found = crawlers.unreviewed(known(decided), {"amazonbot"}, set())
    assert found == []


def test_an_agent_already_weighed_is_not_reported() -> None:
    assert crawlers.unreviewed(known("OldBot"), set(), {"oldbot"}) == []


def test_a_new_agent_is_reported_with_its_operator_and_purpose() -> None:
    [agent] = crawlers.unreviewed(known("BrandNewBot"), {"gptbot"}, {"oldbot"})
    assert agent.name == "BrandNewBot"
    assert agent.render() == "BrandNewBot — BrandNewBot Inc; AI Crawler"


def test_an_entry_without_operator_or_function_still_reports_the_name() -> None:
    [agent] = crawlers.unreviewed({"Mystery": {}}, set(), set())
    assert "operator not stated" in agent.render()


def test_nothing_is_new_today() -> None:
    """The baseline was seeded from the list, so the watch starts quiet by construction."""
    listed = json.loads((ROOT / "infra" / "crawlers-seen.json").read_text(encoding="utf-8"))
    found = crawlers.unreviewed(
        known(*listed["agents"]), crawlers.blocked_tokens(ROOT), crawlers.seen_names(ROOT)
    )
    assert found == []


# --- the expression guard -----------------------------------------------------------------


def test_every_committed_rule_expression_is_under_cloudflares_limit() -> None:
    assert crawlers.over_long_expressions(ROOT) == []


def test_an_expression_over_the_limit_is_refused(tmp_path: Path) -> None:
    """The negative control: the guard fires, and names the rule and the length."""
    rules = tmp_path / "infra" / "rulesets"
    rules.mkdir(parents=True)
    long = "x" * (crawlers.MAX_EXPRESSION_CHARACTERS + 1)
    (rules / "http_request_firewall_custom.json").write_text(
        json.dumps({"rules": [{"ref": "too_long", "expression": long}]})
    )
    [problem] = crawlers.over_long_expressions(tmp_path)
    assert "too_long" in problem
    assert f"{crawlers.MAX_EXPRESSION_CHARACTERS + 1:,}" in problem


# --- reading the list ---------------------------------------------------------------------


class Serving(http.server.BaseHTTPRequestHandler):
    BODIES: ClassVar[dict[str, bytes]] = {
        "/good.json": b'{"NewBot": {"operator": "New"}}',
        "/empty.json": b"{}",
    }

    def do_GET(self) -> None:
        body = self.BODIES.get(self.path, b"<html>not json</html>")
        self.send_response(200 if self.path in self.BODIES or self.path == "/bad.json" else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        pass


@pytest.fixture
def server() -> Iterator[str]:
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Serving)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_a_list_that_reads_is_returned(server: str) -> None:
    assert crawlers.fetch_known(f"{server}/good.json") == {"NewBot": {"operator": "New"}}


@pytest.mark.parametrize("path", ["/empty.json", "/bad.json", "/missing.json"])
def test_a_list_that_is_empty_unparsable_or_absent_raises(server: str, path: str) -> None:
    with pytest.raises(crawlers.WatchError):
        crawlers.fetch_known(f"{server}{path}")


# --- the command's exit codes -------------------------------------------------------------


def run(monkeypatch: pytest.MonkeyPatch, **patches: Any) -> int:
    for name, value in patches.items():
        monkeypatch.setattr(crawlers, name, value)
    return CliRunner().invoke(cli.main, ["crawler-watch", "--json"]).exit_code


def test_nothing_new_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    assert run(monkeypatch, fetch_known=lambda *_a, **_k: known("GPTBot")) == cli.NOTHING_NEW


def test_a_new_agent_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    assert run(monkeypatch, fetch_known=lambda *_a, **_k: known("BrandNewBot")) == cli.NEW_AGENTS


def test_a_list_that_cannot_be_read_exits_three(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> dict[str, Any]:
        raise crawlers.WatchError("no")

    assert run(monkeypatch, fetch_known=boom) == cli.COULD_NOT_READ


def test_an_over_long_expression_exits_four_before_anything_is_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(*_a: object, **_k: object) -> dict[str, Any]:
        raise AssertionError("the guard must fail before the list is read")

    code = run(monkeypatch, over_long_expressions=lambda _r: ["too long"], fetch_known=never)
    assert code == cli.EXPRESSION_TOO_LONG


# --- the workflow -------------------------------------------------------------------------


def job() -> dict[str, Any]:
    return dict(WORKFLOW["jobs"]["crawlers"])


def test_the_advisory_is_left_alone_when_the_list_could_not_be_read() -> None:
    """Exit 3 must reach neither `ok` nor `failing`: the issue stays as it was found."""
    steps = job()["steps"]
    advisory = next(s for s in steps if "advisory" in str(s.get("name", "")))
    condition = str(advisory["if"])
    assert "steps.watch.outputs.code == '0'" in condition
    assert "steps.watch.outputs.code == '1'" in condition
    assert "'3'" not in condition
    assert "--state ${{ steps.watch.outputs.code == '1' && 'failing' || 'ok' }}" in advisory["run"]


def test_the_job_reads_and_reports_but_never_writes_a_rule() -> None:
    runs = " ".join(str(step.get("run", "")) for step in job()["steps"])
    assert "loremfile crawler-watch --json" in runs, "control: the job runs the watch"
    assert "infra apply" not in runs
    assert "--write" not in runs
    assert job().get("environment") is None, "it needs no zone credentials"
    assert "concurrency" not in job(), "nothing remote to serialise on (ADR-029)"
