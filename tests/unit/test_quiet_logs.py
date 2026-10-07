"""What the public run logs and issue bodies may show (docs/09 §4).

Three rules, each with a control that watches it fire:

- the account and zone ids come from `production` environment secrets, so Actions masks
  them, and only jobs in that environment read them;
- the audit and the health check print counts on success and every detail on failure;
- nothing posts either id into an issue: Actions' mask covers the log only.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from loremfile import cli, gh_issue
from loremfile.infra import apply as apply_module
from loremfile.infra import audit as audit_module
from loremfile.infra import tokens as tokens_module
from loremfile.infra import usage as usage_module
from loremfile.infra.audit import DRIFT, NOT_APPLICABLE, OK, UNREADABLE, WARNING, AuditReport
from loremfile.infra.cloudflare_api import Client, CloudflareError, Response, ZoneScopeError

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
IDS = ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_ZONE_ID")
ZONE = "0123456789abcdef0123456789abcdef"
ACCOUNT = "fedcba9876543210fedcba9876543210"
OTHER_ZONE = "aaaaaaaabbbbbbbbccccccccdddddddd"


# --- the ids are environment secrets ----------------------------------------------------


def id_reads(workflow: dict[str, Any]) -> dict[str, set[str]]:
    """{job: the expression roots (`secrets`, `vars`, ...) it reads either id from}."""
    pattern = re.compile(r"\$\{\{\s*(\w+)\.(" + "|".join(IDS) + r")\s*\}\}")
    found: dict[str, set[str]] = {}
    top = json.dumps(workflow.get("env") or {})
    for root, _ in pattern.findall(top):
        found.setdefault("<workflow env>", set()).add(root)
    for name, job in (workflow.get("jobs") or {}).items():
        for root, _ in pattern.findall(json.dumps(job)):
            found.setdefault(name, set()).add(root)
    return found


def problems(workflow: dict[str, Any]) -> list[str]:
    jobs = workflow.get("jobs") or {}
    out = []
    for job, roots in id_reads(workflow).items():
        if roots != {"secrets"}:
            out.append(f"{job} reads the ids from {sorted(roots)}, not only secrets")
        if job == "<workflow env>" or jobs.get(job, {}).get("environment") != "production":
            out.append(f"{job} reads the ids outside the production environment")
    return out


def load(name: str) -> dict[str, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_the_finder_sees_the_jobs_that_read_the_ids() -> None:
    """The control for the rule below: it names jobs, so an empty search cannot pass."""
    seen = {
        (path.name, job) for path in WORKFLOWS.glob("*.yml") for job in id_reads(load(path.name))
    }
    assert {
        ("audit.yml", "infra"),
        ("deploy.yml", "deploy"),
        ("health.yml", "check"),
        ("infra.yml", "apply"),
        ("infra.yml", "probe"),
    } <= seen


def test_every_read_is_a_secret_in_a_production_job() -> None:
    assert {path.name: problems(load(path.name)) for path in WORKFLOWS.glob("*.yml")} == {
        path.name: [] for path in WORKFLOWS.glob("*.yml")
    }


def test_the_rule_fires_on_a_variable_and_on_a_job_outside_the_environment() -> None:
    bad = {
        "env": {"CLOUDFLARE_ZONE_ID": "${{ secrets.CLOUDFLARE_ZONE_ID }}"},
        "jobs": {
            "a": {"environment": "production", "env": {"X": "${{ vars.CLOUDFLARE_ZONE_ID }}"}},
            "b": {"env": {"X": "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"}},
        },
    }
    assert problems(bad) == [
        "<workflow env> reads the ids outside the production environment",
        "a reads the ids from ['vars'], not only secrets",
        "b reads the ids outside the production environment",
    ]


# --- the infra audit --------------------------------------------------------------------


def run_audit(monkeypatch: pytest.MonkeyPatch, report: AuditReport) -> Any:
    monkeypatch.setattr(cli.Client, "from_env", classmethod(lambda _cls, **_k: object()))
    monkeypatch.setattr(cli.audit_infra, "run", lambda _client: report)
    return CliRunner().invoke(cli.main, ["infra", "audit", "--json"])


def test_a_clean_audit_prints_one_line_of_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    report = AuditReport(zone_id=ZONE, hostname="loremfile.dev")
    report.add("setting:ssl", OK, "strict")
    report.add("url-normalization", WARNING, "T1 cannot read it")
    report.add("tiered-cache", NOT_APPLICABLE, "off, not editable")
    result = run_audit(monkeypatch, report)
    assert result.exit_code == 0
    assert result.stderr.strip().splitlines() == [
        "zone loremfile.dev: 3 checked, ok=1 warning=1 not-applicable=1 unreadable=0 drift=0"
    ]
    assert "zone_id" not in json.loads(result.stdout)["summary"]


@pytest.mark.parametrize("state", [DRIFT, UNREADABLE])
def test_a_drifting_or_unreadable_audit_prints_every_finding(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    """The control: quiet on success must not mean quiet when it matters."""
    report = AuditReport(zone_id=ZONE, hostname="loremfile.dev")
    report.add("setting:ssl", OK, "strict")
    report.add("setting:always_use_https", state, "is 'off', wants 'on'")
    stderr = run_audit(monkeypatch, report).stderr
    assert "setting:ssl" in stderr
    assert "setting:always_use_https" in stderr
    assert "is 'off', wants 'on'" in stderr
    assert stderr == report.render() + "\n"
    assert ZONE not in stderr


# --- the health check: usage and tokens-due ---------------------------------------------


def operations() -> usage_module.Operations:
    def row(action: str, status: str, requests: int) -> dict[str, Any]:
        return {
            "dimensions": {"actionType": action, "actionStatus": status},
            "sum": {"requests": requests},
        }

    return usage_module.Operations(
        rows=[row("GetObject", "success", 1200), row("HeadObject", "success", 300)]
    )


SCANNERS = {
    "from": "2026-10-01",
    "to": "2026-10-06",
    "days": [
        {"date": "2026-10-01", "scanner_requests": 7, "requests": 2000},
        {"date": "2026-10-02", "scanner_requests": 9, "requests": 2100},
    ],
    "scanner_requests": 16,
    "requests": 4100,
    "share": 16 / 4100,
    "unsampled": False,
}


def run_usage(monkeypatch: pytest.MonkeyPatch, *, series_fails: bool) -> Any:
    monkeypatch.setattr(usage_module, "month_to_date", operations)
    monkeypatch.setattr(usage_module, "scanner_days", lambda: [])
    monkeypatch.setattr(usage_module, "scanner_summary", lambda _found: SCANNERS)

    def recent_days(_days: int) -> list[Any]:
        if series_fails:
            raise usage_module.UsageError("daily series refused")
        return []

    monkeypatch.setattr(usage_module, "recent_days", recent_days)
    return CliRunner().invoke(cli.main, ["usage", "--json", "--daily-days", "2"])


def test_a_clean_usage_read_prints_counts_only(monkeypatch: pytest.MonkeyPatch) -> None:
    stderr = run_usage(monkeypatch, series_fails=False).stderr
    assert len(stderr.strip().splitlines()) == 2, stderr
    assert "R2 operations:" in stderr
    assert "scanner paths, 2026-10-01 to 2026-10-06" in stderr
    assert "HeadObject" not in stderr
    assert "2026-10-02 " not in stderr


def test_a_failed_usage_read_prints_every_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control: a read that failed keeps the whole breakdown in the log."""
    stderr = run_usage(monkeypatch, series_fails=True).stderr
    assert "HeadObject" in stderr
    assert "GetObject" in stderr
    assert "2026-10-02 " in stderr


def test_over_the_threshold_the_workflow_prints_every_row(tmp_path: Path) -> None:
    """health.yml prints this when R2 reads cross the cost threshold."""
    from loremfile.infra import usage_detail  # noqa: PLC0415

    document = {
        "summary": {"r2_class_b_mtd": 6_000_000},
        "items": [
            {"path": "GetObject/success", "status": "counted", "detail": "6000000"},
            {"path": "HeadObject/success", "status": "counted", "detail": "300"},
        ],
        "errors": [],
        "scanner_paths": SCANNERS,
    }
    text = usage_module.render_detail(document)
    for needle in ("r2_class_b_mtd: 6000000", "GetObject/success", "HeadObject/success"):
        assert needle in text
    assert "2026-10-01 " in text and "2026-10-02 " in text
    report = tmp_path / "usage.json"
    report.write_text(json.dumps(document))
    assert usage_detail.main([str(report)]) == 0


def expiry(name: str, days_left: int) -> tokens_module.Expiry:
    today = dt.date(2026, 10, 7)
    return tokens_module.Expiry(
        key=name, name=name, expires=today + dt.timedelta(days=days_left), days_left=days_left
    )


def test_tokens_due_is_one_line_when_nothing_is_due(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.tokens_module, "tokens_due", lambda: [expiry("T1 zone", 120)])
    stderr = CliRunner().invoke(cli.main, ["tokens-due", "--json"]).stderr
    assert stderr.strip().splitlines() == ["1 tokens, none due"]


def test_tokens_due_prints_every_row_once_one_is_due(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control for the line above."""
    rows = [expiry("T1 zone", 120), expiry("T4 analytics", 5)]
    monkeypatch.setattr(cli.tokens_module, "tokens_due", lambda: rows)
    stderr = CliRunner().invoke(cli.main, ["tokens-due", "--json"]).stderr
    assert "T1 zone" in stderr
    assert "T4 analytics" in stderr
    assert "<-- rotate" in stderr


# --- nothing posts the ids into an issue ------------------------------------------------


class Recorder:
    """`subprocess.run` for gh, recording argv: the real `_gh` builds the real call."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[list[str]] = []
        monkeypatch.setattr(gh_issue.shutil, "which", lambda _name: "/usr/bin/gh")
        monkeypatch.setattr(gh_issue.subprocess, "run", self._run)

    def _run(self, argv: list[str], **_kwargs: object) -> object:
        self.calls.append(list(argv))
        stdout = "[]" if argv[2] == "list" else "https://github.com/o/r/issues/1"
        return gh_issue.subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    def body(self) -> str:
        [create] = [argv for argv in self.calls if argv[2] == "create"]
        return create[create.index("--body") + 1]


def leaky_report(tmp_path: Path) -> Path:
    report = tmp_path / "audit.json"
    report.write_text(
        json.dumps(
            {
                "command": "infra audit",
                "ok": False,
                "summary": {"zone": "loremfile.dev", "zone_id": ZONE},
                "errors": [f"GET /accounts/{ACCOUNT}/r2/buckets/x/lock: 403"],
            }
        )
    )
    return report


def test_an_issue_body_never_carries_the_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("CLOUDFLARE_ZONE_ID", ZONE)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    gh = Recorder(monkeypatch)
    gh_issue.apply(label="infra-drift", title="t", report=leaky_report(tmp_path), state="failing")
    body = gh.body()
    assert ZONE not in body and ACCOUNT not in body
    assert body.count(gh_issue.MASK) == 2
    assert "loremfile.dev" in body


def test_the_mask_is_what_removed_them(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The control: without the values in the environment, the same report leaks."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.delenv("CLOUDFLARE_ZONE_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    gh = Recorder(monkeypatch)
    gh_issue.apply(label="infra-drift", title="t", report=leaky_report(tmp_path), state="failing")
    assert ZONE in gh.body()


# --- the client's messages name no id ---------------------------------------------------


class Zone(Client):
    """A client whose zone answers with `name`; never a socket."""

    def __init__(self, name: str, *, ok: bool = True) -> None:
        super().__init__(token="not-a-token", zone_id=ZONE, account_id=ACCOUNT)  # noqa: S106
        self.name, self.reachable = name, ok

    def _send(self, _method: str, path: str, _payload: dict[str, Any] | None) -> Response:
        if not self.reachable:
            return Response(403, {"success": False, "errors": [{"message": "denied"}]})
        if path.startswith("/zones/") and "page=" in path:
            return Response(403, {"success": False, "errors": [{"message": "denied"}]})
        return Response(200, {"success": True, "result": {"name": self.name}})


def message(call: Any) -> str:
    try:
        call()
    except (ZoneScopeError, CloudflareError) as exc:
        return str(exc)
    raise AssertionError("expected the guard to refuse")


def test_the_zone_guard_names_neither_id_nor_the_other_zone() -> None:
    texts = [
        message(Zone("unrelated.example").verify_zone),
        message(Zone("loremfile.dev", ok=False).verify_zone),
    ]
    verified = Zone("loremfile.dev")
    verified.verify_zone()
    texts.append(message(lambda: verified.put(f"/zones/{OTHER_ZONE}/settings/ssl", {})))
    texts.append(message(lambda: verified.put(f"/accounts/{OTHER_ZONE}/r2/x", {})))
    texts.append(message(lambda: verified.paginate(f"/zones/{ZONE}/dns_records")))
    assert len(texts) == 5
    for text in texts:
        for secret in (ZONE, ACCOUNT, OTHER_ZONE, "unrelated.example"):
            assert secret not in text, text
    assert "/zones/{another zone}/settings/ssl" in texts[2]
    assert "/zones/{zone}/dns_records" in texts[4]


# --- the deploy's infra dry-run ---------------------------------------------------------


def run_apply(monkeypatch: pytest.MonkeyPatch, report: apply_module.Report) -> Any:
    monkeypatch.setattr(cli.Client, "from_env", classmethod(lambda _cls, **_k: object()))
    monkeypatch.setattr(cli.apply_infra, "run", lambda _client: report)
    return CliRunner().invoke(cli.main, ["infra", "apply", "--dry-run"])


def test_an_apply_with_nothing_to_do_prints_one_line_of_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = apply_module.Report(zone_id=ZONE, hostname="loremfile.dev")
    for index in range(35):
        report.add(f"setting:s{index}", "unchanged")
    report.add("setting:polish", "skipped", "read-only, is 'off'")
    result = run_apply(monkeypatch, report)
    assert result.exit_code == 0
    assert result.stderr.strip().splitlines() == [
        "zone loremfile.dev: 36 resources, unchanged=35 skipped=1 updated=0 manual=0 "
        "warning=0 failed=0"
    ]
    assert ZONE not in result.stdout + result.stderr
    assert "zone_id" not in result.stdout


@pytest.mark.parametrize("state", sorted(apply_module.LOUD))
def test_an_apply_with_anything_to_do_prints_every_row(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    """The control: one row in any loud state brings back every row."""
    report = apply_module.Report(zone_id=ZONE, hostname="loremfile.dev")
    report.add("setting:ssl", "unchanged")
    report.add("url-normalization", state, "Rules → Settings → Normalize incoming URLs")
    stderr = run_apply(monkeypatch, report).stderr
    assert stderr.startswith(report.render() + "\n")
    assert "setting:ssl" in stderr
    assert ZONE not in stderr


class Refused:
    """A zone whose URL normalization endpoint answers `status` with `errors`."""

    zone_id = ZONE
    account_id = ACCOUNT

    def __init__(self, status: int, errors: list[dict[str, Any]]) -> None:
        self.reply = Response(status, {"success": False, "errors": errors})

    def get(self, _path: str) -> Response:
        return self.reply


@pytest.mark.parametrize(
    ("status", "errors", "said"),
    [
        (
            403,
            [{"code": 10000, "message": "Authentication error"}],
            "HTTP 403, 10000: Authentication error",
        ),
        (404, [], "(HTTP 404)"),
    ],
)
def test_url_normalization_says_how_it_was_refused(
    status: int, errors: list[dict[str, Any]], said: str
) -> None:
    """A 403 is the token's scope and a 404 the endpoint: both readers now say which."""
    applied = apply_module.Report()
    apply_module.apply_url_normalization(Refused(status, errors), applied)  # type: ignore[arg-type]
    audited = AuditReport()
    audit_module.audit_url_normalization(Refused(status, errors), audited)  # type: ignore[arg-type]
    assert [(o.state, said in o.detail) for o in applied.outcomes] == [("manual", True)]
    assert [(f.state, said in f.detail) for f in audited.findings] == [(UNREADABLE, True)]
