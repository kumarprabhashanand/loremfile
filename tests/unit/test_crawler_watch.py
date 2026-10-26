"""The weekly crawler watch: what it reports, and what it must never do (docs/09 §3.4).

Two properties carry the weight. A run that could not read the list must leave the advisory
issue alone — reporting `ok` there would close a real advisory on a run that learned nothing
(`11` §7.2) — and the watch never edits a rule, because blocking an agent is a decision.
"""

from __future__ import annotations

import http.server
import json
import re
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


def test_a_deferred_name_is_weighed_and_carries_its_reasons() -> None:
    """nbot (#96): deferred, not blocked. The record says why and what would reopen it."""
    deferred = json.loads((ROOT / crawlers.SEEN_FILE).read_text(encoding="utf-8"))["deferred"]
    entry = deferred["nbot"]
    assert len(entry["reasons"]) == 2
    assert "Amazonbot" in entry["reasons"][0]
    assert "msnbot" in entry["reasons"][0]
    assert "publishes none" in entry["reasons"][1]
    assert "exact match" in entry["reopen"]
    assert (
        crawlers.unreviewed(known("nbot"), crawlers.blocked_tokens(ROOT), crawlers.seen_names(ROOT))
        == []
    )


def test_control_without_the_deferral_nbot_would_be_reported() -> None:
    """It is weighed, not blocked: drop the seen names and the watch raises it again."""
    [agent] = crawlers.unreviewed(known("nbot"), crawlers.blocked_tokens(ROOT), set())
    assert agent.name == "nbot"


#: The five #110 weighed on 2026-10-26 and did not block, with the guard in docs/04 §6 each
#: fell under: one substring collision, four display names the list publishes beside tokens.
DEFERRED_2026_10_26 = {
    "Dot": "first guard",
    "AGI Agent": "third guard",
    "CartAI Agentic Commerce": "third guard",
    "Grok Bot": "third guard",
    "Payhawk Invoice Fetching Agent": "third guard",
}


@pytest.mark.parametrize(("name", "guard"), sorted(DEFERRED_2026_10_26.items()))
def test_each_name_deferred_on_2026_10_26_is_weighed_and_says_which_guard(
    name: str, guard: str
) -> None:
    """Deferred, not blocked, and not raised again: the record carries the date, the issue,
    the guard it fell under and what would reopen it."""
    deferred = json.loads((ROOT / crawlers.SEEN_FILE).read_text(encoding="utf-8"))["deferred"]
    entry = deferred[name]
    assert entry["weighed"] == "2026-10-26"
    assert entry["issue"] == "#110"
    assert guard in " ".join(entry["reasons"])
    assert "ADR-033" in entry["reopen"]
    assert (
        crawlers.unreviewed(known(name), crawlers.blocked_tokens(ROOT), crawlers.seen_names(ROOT))
        == []
    )


@pytest.mark.parametrize("name", sorted(DEFERRED_2026_10_26))
def test_control_without_the_deferral_each_of_the_five_would_be_reported(name: str) -> None:
    """Weighed, not blocked: `Grok Bot` is the one to watch, because `grokbot` *is* blocked and
    the two are different names."""
    [agent] = crawlers.unreviewed(known(name), crawlers.blocked_tokens(ROOT), set())
    assert agent.name == name


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


RECORDED = re.compile(r"([\d,]+) characters and (\d+) tokens, ([\d.]+)% of the limit")


def recorded_baseline(text: str) -> tuple[int, int, float]:
    """The latest figure docs/04 §6's Baseline bullet records, as it is written there."""
    found = RECORDED.findall(text)
    assert found, "empty-set control: §6 records at least one baseline"
    characters, tokens, percent = found[-1]
    return int(characters.replace(",", "")), int(tokens), float(percent)


def test_the_baseline_docs_04_records_is_the_committed_expression_measured() -> None:
    """§6 says to measure with `len()` and record each change so the trend is read rather than
    re-measured. A figure nobody holds to the rule goes stale on the first addition that forgets
    it, and the budget decision is taken off that figure."""
    expression = next(
        rule["expression"]
        for rule in json.loads(
            (ROOT / "infra" / "rulesets" / "http_request_firewall_custom.json").read_text(
                encoding="utf-8"
            )
        )["rules"]
        if rule["ref"] == "loremfile_legal_pages_ai_agents"
    )
    section = (ROOT / "docs" / "04-manifest-and-discovery.md").read_text(encoding="utf-8")
    tokens = len(crawlers.TOKEN.findall(expression))
    percent = round(len(expression) / crawlers.MAX_EXPRESSION_CHARACTERS * 100, 1)
    assert recorded_baseline(section) == (len(expression), tokens, percent)


def test_the_baseline_reader_takes_the_last_figure_recorded() -> None:
    """The negative control: it parses, and an older figure earlier in the bullet is not it."""
    assert recorded_baseline(
        "1,390 characters and 26 tokens, 33.9% of the limit. "
        "**1,668 characters and 33 tokens, 40.7% of the limit**"
    ) == (1668, 33, 40.7)


def rules_of(tmp_path: Path, length: int) -> Path:
    rules = tmp_path / "infra" / "rulesets"
    rules.mkdir(parents=True)
    (rules / "http_request_firewall_custom.json").write_text(
        json.dumps({"rules": [{"ref": "growing", "expression": "x" * length}]})
    )
    return tmp_path


def test_every_committed_rule_expression_is_under_the_budget_line() -> None:
    """docs/04 §6: past 75% of the limit, adding tokens is the reviewer's call. A pull request
    that crosses the line fails here, which is where the escalation starts."""
    assert crawlers.BUDGET_CHARACTERS == 3072
    assert crawlers.over_budget_expressions(ROOT) == []


def test_control_the_budget_scan_reads_the_committed_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test above would pass on a scan that found nothing; lowered, the line must name it."""
    monkeypatch.setattr(crawlers, "BUDGET_CHARACTERS", 1000)
    [problem] = crawlers.over_budget_expressions(ROOT)
    assert "loremfile_legal_pages_ai_agents" in problem


@pytest.mark.parametrize(
    ("length", "reported"),
    [
        (crawlers.BUDGET_CHARACTERS, False),
        (crawlers.BUDGET_CHARACTERS + 1, True),
        (crawlers.MAX_EXPRESSION_CHARACTERS, True),
        # Over the limit is the other guard's finding, and exit 4, not a budget warning.
        (crawlers.MAX_EXPRESSION_CHARACTERS + 1, False),
    ],
)
def test_the_budget_line_fires_just_past_three_quarters(
    tmp_path: Path, length: int, *, reported: bool
) -> None:
    problems = crawlers.over_budget_expressions(rules_of(tmp_path, length))
    assert bool(problems) is reported
    if reported:
        assert "growing" in problems[0]
        assert f"{length:,} of 4,096" in problems[0]


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


def test_a_rule_past_the_budget_line_exits_one_with_nothing_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code = run(
        monkeypatch,
        fetch_known=lambda *_a, **_k: known("GPTBot"),
        over_budget_expressions=lambda _r: ["past the 3,072 budget line"],
    )
    assert code == cli.NEW_AGENTS


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
