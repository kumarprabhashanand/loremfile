"""M4.4: the audit reports state, and `apply` reports the write.

The distinction is the whole point. `apply` PUTs every ruleset phase unconditionally, so
it says `updated` on every run whether or not anything differed — six resources do this.
An audit that reused those outcomes would open an `infra-drift` issue weekly, and a label
that fires every run stops meaning anything. These tests are mostly about that: that the
audit is comparing content, and that it cannot write even if someone later wishes it did.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from typing import Any

import pytest

from loremfile.infra import apply as apply_module
from loremfile.infra import audit
from loremfile.infra.audit import DRIFT, OK, UNREADABLE, AuditReport, compare_rules
from loremfile.infra.cloudflare_api import Client, CloudflareError, ReadOnlyError, Response


def response(body: Any, status: int = 200) -> Response:
    return Response(status=status, body={"success": status == 200, "result": body, "errors": []})


class FakeZone:
    """Answers GETs from a dict of paths; records everything asked of it."""

    def __init__(self, answers: dict[str, Response]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def get(self, path: str) -> Response:
        self.asked.append(path)
        for suffix, reply in self.answers.items():
            if path.endswith(suffix):
                return reply
        return response(None, status=404)

    zone_id = "z"


# --- the comparison ---------------------------------------------------------


def rule(description: str, expression: str, **extra: Any) -> dict[str, Any]:
    return {"description": description, "expression": expression, "action": "set_config", **extra}


def deployed(base: dict[str, Any], **server: Any) -> dict[str, Any]:
    """What Cloudflare stores: our rule plus the fields it assigns."""
    return {
        **base,
        "id": "3f2c" * 8,
        "version": "7",
        "ref": "abc123",
        "last_updated": "2026-09-10T00:00:00Z",
    } | server


def test_server_assigned_fields_are_not_drift() -> None:
    """Otherwise every rule differs forever and the audit is noise from day one."""
    want = [rule("H1", 'starts_with(http.request.uri.path, "/")')]
    assert compare_rules(want, [deployed(want[0])]) == []


def test_a_changed_expression_is_drift_and_names_the_rule() -> None:
    want = [rule("H1", 'starts_with(http.request.uri.path, "/")')]
    have = [deployed(rule("H1", 'starts_with(http.request.uri.path, "/other")'))]
    (found,) = compare_rules(want, have)
    assert "H1" in found
    assert "expression" in found


def test_a_field_cloudflare_added_on_its_own_is_not_reported() -> None:
    """Stated in the module docstring rather than left as a surprise: we compare the
    fields we declared. A default Cloudflare filled in is not ours to have an opinion
    about, and reporting it would be indistinguishable from real drift."""
    want = [rule("H1", "true")]
    have = [deployed(rule("H1", "true"), logging={"enabled": False})]
    assert compare_rules(want, have) == []


def test_order_is_part_of_the_meaning() -> None:
    """Rules evaluate top to bottom, so a swap changes behaviour and must be drift."""
    a, b = rule("first", "true"), rule("second", "false")
    assert compare_rules([a, b], [deployed(b), deployed(a)]) != []


def test_a_missing_rule_and_an_extra_rule_are_both_reported() -> None:
    a, b = rule("first", "true"), rule("second", "false")
    missing = compare_rules([a, b], [deployed(a)])
    assert any("missing" in d for d in missing)

    extra = compare_rules([a], [deployed(a), deployed(b)])
    assert any("extra rule deployed" in d for d in extra)


# --- what the checks report -------------------------------------------------


def test_a_phase_that_matches_reports_ok_not_updated() -> None:
    """The whole reason this module exists. `apply` says `updated` here, every run."""
    phase = apply_module.WRITTEN_PHASES[0]
    committed = apply_module.load_desired(f"rulesets/{phase}.json")["rules"]
    zone = FakeZone(
        {
            f"phases/{phase}/entrypoint": response({"rules": [deployed(r) for r in committed]}),
            "/rulesets": response([{"phase": apply_module.MANAGED_PHASE, "kind": "managed"}]),
        }
    )
    report = AuditReport()
    audit.audit_rulesets(zone, report)  # type: ignore[arg-type]

    first = report.findings[0]
    assert first.resource == phase
    assert first.state == OK, "a matching phase must not be reported as changed"
    assert "match" in first.detail


def test_an_unreadable_resource_is_a_warning_not_a_failure() -> None:
    """docs/09 §3.4. A permission that cannot read a setting says nothing about whether
    the setting is right; failing on it makes the audit useless on the days it matters."""
    report = AuditReport()
    report.add("bot-management", UNREADABLE, "403")
    assert report.ok
    assert not report.drifted
    assert report.unreadable


def test_real_drift_is_not_ok() -> None:
    """Negative control for the test above: `ok` must not be a constant."""
    report = AuditReport()
    report.add("setting:ssl", DRIFT, "is 'flexible', want 'strict'")
    assert not report.ok


def test_tiered_cache_is_read_rather_than_written() -> None:
    """`apply` PATCHes it unconditionally and always reports `updated`; the audit has to
    look at the value instead."""
    zone = FakeZone({"tiered_cache_smart_topology_enable": response({"value": "on"})})
    report = AuditReport()
    audit.audit_tiered_cache(zone, report)  # type: ignore[arg-type]
    assert report.findings[0].state == OK

    off = FakeZone({"tiered_cache_smart_topology_enable": response({"value": "off"})})
    report = AuditReport()
    audit.audit_tiered_cache(off, report)  # type: ignore[arg-type]
    assert report.findings[0].state == DRIFT


def test_a_wrong_zone_setting_is_named_with_both_values() -> None:
    desired = apply_module.load_desired("zone-settings.json")
    key = next(iter(desired))
    settings = [{"id": k, "value": v, "editable": True} for k, v in desired.items()]
    settings[0] = {**settings[0], "value": "definitely-not-it"}
    zone = FakeZone({"/settings": response(settings)})

    report = AuditReport()
    audit.audit_zone_settings(zone, report)  # type: ignore[arg-type]
    drifted = report.drifted
    assert [f.resource for f in drifted] == [f"setting:{key}"]
    assert "definitely-not-it" in drifted[0].detail
    assert json.dumps(desired[key]).strip('"') in drifted[0].detail


# --- it cannot write --------------------------------------------------------


def test_a_read_only_client_refuses_every_write() -> None:
    client = Client(token="t", zone_id="z", account_id="a", read_only=True)  # noqa: S106
    client.verified_hostname = "loremfile.dev"
    for method in ("PUT", "PATCH", "POST", "DELETE"):
        with pytest.raises(ReadOnlyError, match="read-only"):
            client.request(method, "/zones/z/settings/ssl", {"value": "strict"})
    assert client.calls == [], "a refused write must not even be recorded as attempted"


def test_a_read_only_client_still_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control: a client that refused *everything* would pass the test above,
    and would also make the audit useless. The GET has to reach the transport."""
    client = Client(token="t", zone_id="z", account_id="a", read_only=True)  # noqa: S106
    sent: list[tuple[str, str]] = []

    def send(method: str, path: str, _payload: object) -> Response:
        sent.append((method, path))
        return response({"ok": True})

    monkeypatch.setattr(client, "_send", send)
    assert client.get("/zones/z/settings").ok
    assert sent == [("GET", "/zones/z/settings")]


def test_no_audit_check_calls_a_write_method() -> None:
    """The structural half of the same guarantee.

    `audit.yml` runs with T1 because Cloudflare tokens cannot be split read/write per
    call, so the audit holds a token that *could* write. The read-only client refuses at
    run time; this refuses at review time, and names the offender.
    """
    source = textwrap.dedent(inspect.getsource(audit))
    tree = ast.parse(source)
    writes = {"put", "patch", "post", "delete"}
    offenders = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in writes
    ]
    assert offenders == [], f"audit.py calls {offenders}; the audit reports, it does not converge"


def test_the_audit_covers_every_resource_apply_writes() -> None:
    """An audit that silently skipped a resource would report a clean zone for a zone it
    never looked at — worse than reporting drift, because it looks like good news."""
    applied = {step.__name__.removeprefix("apply_") for step in apply_module.STEPS}
    audited = {check.__name__.removeprefix("audit_") for check in audit.CHECKS}
    assert applied == audited, f"not audited: {sorted(applied - audited)}"


# --- three outcomes, not two ------------------------------------------------


def audit_exit(monkeypatch: pytest.MonkeyPatch, outcome: object) -> int:
    """Run `infra audit` against a stubbed `audit.run` and return its exit code."""
    from click.testing import CliRunner  # noqa: PLC0415 - only this group of tests needs it

    from loremfile import cli  # noqa: PLC0415

    monkeypatch.setattr(
        cli.Client,
        "from_env",
        classmethod(lambda _cls, **_k: object()),  # type: ignore[arg-type]
    )

    def run(_client: object) -> AuditReport:
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, AuditReport)
        return outcome

    monkeypatch.setattr(cli.audit_infra, "run", run)
    return CliRunner().invoke(cli.main, ["infra", "audit", "--json"]).exit_code


def test_a_clean_audit_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    report = AuditReport(zone_id="z", hostname="loremfile.dev")
    report.add("setting:ssl", OK)
    assert audit_exit(monkeypatch, report) == 0


def test_drift_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    report = AuditReport(zone_id="z", hostname="loremfile.dev")
    report.add("setting:ssl", DRIFT, "is 'flexible'")
    assert audit_exit(monkeypatch, report) == 1


def test_an_audit_that_could_not_run_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    """The distinction the workflow depends on. An audit that could not run has learned
    **nothing** about drift, so `audit.yml` leaves the drift issue alone on a 2 — otherwise
    a rotated token would close a genuine drift issue by reporting `ok`."""
    from loremfile.infra.cloudflare_api import ZoneScopeError  # noqa: PLC0415

    assert audit_exit(monkeypatch, ZoneScopeError("wrong zone")) == 2
    assert audit_exit(monkeypatch, CloudflareError("token expired")) == 2


def test_unreadable_resources_alone_do_not_make_it_exit_non_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 403 on one setting is a warning (docs/09 §3.4); it is not "could not run"."""
    report = AuditReport(zone_id="z", hostname="loremfile.dev")
    report.add("bot-management", UNREADABLE, "403")
    report.add("setting:ssl", OK)
    assert audit_exit(monkeypatch, report) == 0
