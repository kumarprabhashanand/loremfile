"""The scanner-paths custom rule, its probe, and the measurement of what it removes.

docs/08 §5.7. The rule must block the paths it names and never anything under
`/.well-known/`. Both are asserted against the **committed** expression through a small
evaluator of its own, so these tests do not only compare the module with itself.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

import pytest

from loremfile.infra import probe, scanners, usage
from loremfile.infra.apply import custom_rules_desired
from loremfile.infra.probe import Fetched
from loremfile.site import routes

TERM = re.compile(
    r'starts_with\(http\.request\.uri\.path, "(?P<prefix>[^"]+)"\)'
    r'|http\.request\.uri\.path eq "(?P<exact>[^"]+)"'
)
WELL_KNOWN = [
    "/.well-known/",
    "/.well-known/security.txt",
    f"/{routes.API_CATALOG_KEY}",
    f"/{routes.AGENT_SKILLS_INDEX_KEY}",
]


def committed() -> dict[str, Any]:
    return next(r for r in custom_rules_desired() if r["ref"] == scanners.RULE_REF)


def evaluate(expression: str, path: str) -> bool:
    """`expression` applied to `path`: a disjunction of `starts_with` and `eq` terms only.

    Anything else in the expression fails here rather than being evaluated loosely, so a
    rule that grew an operator this cannot read is a failing test, not a silent pass.
    """
    inner = expression.strip()
    assert inner.startswith("(") and inner.endswith(")"), expression
    parts = inner[1:-1].split(" or ")
    terms = [TERM.fullmatch(part) for part in parts]
    assert all(terms), f"a term this evaluator cannot read: {parts}"
    return any(
        path.startswith(t["prefix"]) if t["prefix"] else path == t["exact"]
        for t in terms
        if t is not None
    )


# --- the committed rule ----------------------------------------------------------------


def test_the_committed_rule_is_the_one_the_module_describes() -> None:
    rule = committed()
    assert rule["expression"] == scanners.expression()
    assert rule["action"] == "block"
    assert rule["enabled"] is True


def test_it_blocks_every_path_it_names() -> None:
    expression = committed()["expression"]
    named = [*scanners.EXACT, "/wp-admin/", "/wp-admin/install.php", "/.git/", "/.git/config"]
    for path in named:
        assert evaluate(expression, path), path
        assert scanners.matches(path), path


def test_it_never_matches_well_known() -> None:
    """security.txt, the API catalog and the agent skills live there (docs/04)."""
    expression = committed()["expression"]
    for path in WELL_KNOWN:
        assert not evaluate(expression, path), path
        assert not scanners.matches(path), path


def test_its_prefixes_are_anchored_at_their_slash() -> None:
    expression = committed()["expression"]
    for path in ("/wp-admin", "/.gitignore", "/.github/workflows/ci.yml", "/.envrc", "/wp-login"):
        assert not evaluate(expression, path), path
        assert not scanners.matches(path), path


def test_it_leaves_fixtures_and_pages_alone() -> None:
    expression = committed()["expression"]
    for path in ("/", "/pdf/minimal.pdf", "/docs/getting-started", "/robots.txt", "/llms.txt"):
        assert not evaluate(expression, path), path


@pytest.mark.parametrize(
    ("expression", "path"),
    [
        (scanners.expression().replace('"/.git/"', '"/.well"'), "/.well-known/security.txt"),
        (scanners.expression().replace('"/wp-admin/"', '"/wp-admin"'), "/wp-admin"),
    ],
)
def test_the_evaluator_reports_a_rule_that_overreaches(expression: str, path: str) -> None:
    """The controls: a widened prefix is caught by the same evaluator the tests above use."""
    assert evaluate(expression, path)


def test_the_evaluator_refuses_an_operator_it_cannot_read() -> None:
    with pytest.raises(AssertionError, match="cannot read"):
        evaluate('(http.request.uri.path contains "wp")', "/wp")


# --- the measurement counts what the rule blocks -----------------------------------------


def test_the_analytics_filter_names_the_same_paths() -> None:
    terms = scanners.analytics_filter()
    exact = {t["clientRequestPath"] for t in terms if "clientRequestPath" in t}
    like = {t["clientRequestPath_like"] for t in terms if "clientRequestPath_like" in t}
    assert exact == set(scanners.EXACT)
    assert like == {f"{prefix}%" for prefix in scanners.PREFIXES}
    for pattern in [*exact, *(p.removesuffix("%") for p in like)]:
        assert "%" not in pattern and "_" not in pattern, f"{pattern} would be a wildcard"


def answering(per_day: dict[str, tuple[int, int, float | None]]) -> tuple[Any, list[dict]]:
    """A GraphQL endpoint: (everything, scanners, sample interval) per day start."""
    sent: list[dict[str, Any]] = []

    def post(_token: str, payload: dict[str, Any], **_: Any) -> dict[str, Any]:
        sent.append(payload)
        everything, scanned, interval = per_day[payload["variables"]["start"][:10]]
        if "sampleInterval" in payload["query"]:
            if interval is None:
                raise usage.UsageError("GraphQL returned errors: unknown field sampleInterval")
            groups = [{"avg": {"sampleInterval": interval}}]
            return {"data": {"viewer": {"zones": [{"httpRequestsAdaptiveGroups": groups}]}}}
        zone = {"everything": [{"count": everything}], "scanners": [{"count": scanned}]}
        return {"data": {"viewer": {"zones": [zone]}}}

    return post, sent


NOW = dt.datetime(2026, 10, 2, 9, 30, tzinfo=dt.UTC)
DAYS = ["2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"]


@pytest.fixture
def zone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDFLARE_ANALYTICS_TOKEN", "not-a-token")
    monkeypatch.setenv("CLOUDFLARE_ZONE_ID", "z")


@pytest.mark.usefixtures("zone")
def test_six_complete_utc_days_are_counted_and_today_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post, sent = answering(dict.fromkeys(DAYS, (1000, 20, 1.0)))
    monkeypatch.setattr(usage, "_post", post)
    found = usage.scanner_days(now=NOW)
    assert [day.date for day in found] == DAYS
    windows = {(p["variables"]["start"], p["variables"]["end"]) for p in sent}
    assert ("2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z") in windows
    assert all(start[:10] != "2026-10-02" for start, _ in windows), "a partial day was counted"


@pytest.mark.usefixtures("zone")
def test_the_query_filters_on_the_rules_own_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    post, sent = answering(dict.fromkeys(DAYS, (1, 0, 1.0)))
    monkeypatch.setattr(usage, "_post", post)
    usage.scanner_days(now=NOW)
    counting = next(p["query"] for p in sent if "scanners:" in p["query"])
    for term in scanners.analytics_filter():
        [(key, value)] = term.items()
        assert f"{key}: {json.dumps(value)}" in counting
    assert counting.count('requestSource: "eyeball"') == 2


@pytest.mark.usefixtures("zone")
def test_the_share_is_exact_over_the_days_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    post, _ = answering({day: (1000, 20 + i, 1.0) for i, day in enumerate(DAYS)})
    monkeypatch.setattr(usage, "_post", post)
    summary = usage.scanner_summary(usage.scanner_days(now=NOW))
    assert summary["requests"] == 6000
    assert summary["scanner_requests"] == 20 * 6 + 15
    assert summary["share"] == pytest.approx(135 / 6000)
    assert (summary["from"], summary["to"]) == (DAYS[0], DAYS[-1])
    assert summary["unsampled"] is True


@pytest.mark.usefixtures("zone")
def test_a_sampled_day_is_said_to_be_an_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    post, _ = answering({day: (1000, 20, 10.0 if day == DAYS[2] else 1.0) for day in DAYS})
    monkeypatch.setattr(usage, "_post", post)
    summary = usage.scanner_summary(usage.scanner_days(now=NOW))
    assert summary["unsampled"] is False
    assert "SAMPLED" in usage.render_scanners(summary)


@pytest.mark.usefixtures("zone")
def test_an_unreadable_sample_interval_costs_only_that(monkeypatch: pytest.MonkeyPatch) -> None:
    post, _ = answering(dict.fromkeys(DAYS, (1000, 20, None)))
    monkeypatch.setattr(usage, "_post", post)
    summary = usage.scanner_summary(usage.scanner_days(now=NOW))
    assert summary["scanner_requests"] == 120, "the counts survived"
    assert summary["unsampled"] is None
    assert "sampling unknown" in usage.render_scanners(summary)


def test_a_failed_measurement_never_fails_the_usage_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It is reported beside the cost check, and must not be able to redden it."""
    from click.testing import CliRunner  # noqa: PLC0415

    from loremfile import cli  # noqa: PLC0415

    def broken(*_a: Any, **_k: Any) -> Any:
        raise usage.UsageError("GraphQL returned errors: no such field")

    monkeypatch.setattr(usage, "operations", lambda *_a, **_k: usage.Operations(rows=[]))
    monkeypatch.setattr(usage, "month_to_date", lambda: usage.Operations(rows=[]))
    monkeypatch.setattr(usage, "scanner_days", broken)
    result = CliRunner().invoke(cli.main, ["usage", "--daily-days", "0", "--json"])
    report = json.loads(result.stdout)
    assert result.exit_code == 0, result.output
    assert report["ok"] is True
    assert report["errors"] == []
    assert "no such field" in report["scanner_paths"]["error"]


# --- the probe ---------------------------------------------------------------------------


@pytest.fixture
def instant_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """`settle` polls for up to 180 s of real time; test_probe.py's own fixture, here."""
    monkeypatch.setattr(probe.time, "sleep", lambda _s: None)
    ticks = iter(range(0, 10_000, 30))
    monkeypatch.setattr(probe.time, "monotonic", lambda: float(next(ticks)))


def refusing(paths: set[str]) -> Any:
    """The edge with the rule in place: 403 on these paths; security.txt served; else 404."""

    def answer(path: str, **_: Any) -> Fetched:
        if path in paths:
            return Fetched(status=403, headers={}, body=b"")
        status = 200 if path.startswith("/.well-known/") else 404
        return Fetched(status=status, headers={}, body=b"")

    return answer


def _scanner_check() -> probe.ProbeReport:
    return probe.run_checks({"scanner-paths": probe.SITE_CHECKS["scanner-paths"]})


def every_target() -> set[str]:
    return {*scanners.EXACT, *(probe.SCANNER_CHILDREN[prefix] for prefix in scanners.PREFIXES)}


@pytest.mark.usefixtures("instant_settle")
def test_the_probe_passes_when_the_rule_refuses_exactly_its_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "fetch", refusing(every_target()))
    report = _scanner_check()
    assert report.ok, report.render()


@pytest.mark.usefixtures("instant_settle")
def test_the_probe_fails_when_well_known_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control that matters: a rule that refuses everything passes every target."""
    monkeypatch.setattr(probe, "fetch", lambda _p, **_: Fetched(status=403, headers={}, body=b""))
    detail = _scanner_check().results[0].detail
    assert "/.well-known/security.txt was refused" in detail


@pytest.mark.usefixtures("instant_settle")
def test_the_probe_fails_when_one_path_is_not_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The last target, so the settle on the first completes and a wrong rule reads as one."""
    targets = [*scanners.EXACT, *(probe.SCANNER_CHILDREN[p] for p in scanners.PREFIXES)]
    monkeypatch.setattr(probe, "fetch", refusing(set(targets[:-1])))
    detail = _scanner_check().results[0].detail
    assert targets[-1] in detail
    assert "precondition unmet" not in detail


@pytest.mark.usefixtures("instant_settle")
def test_a_rule_that_never_arrives_is_reported_as_such(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "fetch", lambda _p, **_: Fetched(status=404, headers={}, body=b""))
    detail = _scanner_check().results[0].detail
    assert "never appeared" in detail
