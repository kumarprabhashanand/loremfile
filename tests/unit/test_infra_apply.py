"""M2.2: apply.py against a fake API, with the zone-scoping guard first (docs/08 §6).

Ruleset entry points are written with a full PUT, and this account holds two unrelated
production zones. A request aimed at the wrong zone id does not drift someone else's
rules — it replaces them. That is the only place in this project where a mistake reaches
something that is not ours, so the guard is tested before the behaviour it guards, and
it is tested for refusal rather than for being present.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from loremfile.infra import apply as apply_module
from loremfile.infra.cloudflare_api import Client, Response, ZoneScopeError

OUR_ZONE = "872580067ef0889f0b978acde39ea205"
OUR_ACCOUNT = "705c5f1733982ab6df37f715f1bafe56"
#: A real, unrelated production zone on the same account. The point of the guard.
OTHER_ZONE = "0000000000000000000000000000beef"
#: S106: there is no credential here; the fake client never opens a socket.
NOT_A_TOKEN = "fake"  # noqa: S105


class FakeClient(Client):
    """Records every call and answers from a canned table, never touching the network."""

    def __init__(self, answers: dict[str, Response] | None = None, **kwargs: Any) -> None:
        super().__init__(token=NOT_A_TOKEN, zone_id=OUR_ZONE, account_id=OUR_ACCOUNT, **kwargs)
        self.answers = answers or {}
        self.writes: list[tuple[str, str, dict[str, Any] | None]] = []

    def _send(self, method: str, path: str, payload: dict[str, Any] | None) -> Response:
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            self.writes.append((method, path, payload))
        key = f"{method} {path.split('?', 1)[0]}"
        if key in self.answers:
            return self.answers[key]
        if path == f"/zones/{OUR_ZONE}":
            return Response(200, {"success": True, "result": {"name": "loremfile.dev"}})
        return Response(200, {"success": True, "result": {}})


def ok(result: Any) -> Response:
    return Response(200, {"success": True, "result": result})


# --- the guard --------------------------------------------------------------


def test_no_write_is_possible_before_the_zone_is_verified() -> None:
    """The default state is refusal, not permission."""
    client = FakeClient()
    with pytest.raises(ZoneScopeError, match="before verify_zone"):
        client.put(f"/zones/{OUR_ZONE}/rulesets/phases/http_request_transform/entrypoint", {})
    assert client.writes == [], "a refused write must not reach the transport"


def test_a_zone_whose_name_is_not_ours_is_refused() -> None:
    """The failure this exists for: the id points at someone else's production zone."""
    client = FakeClient({f"GET /zones/{OUR_ZONE}": ok({"name": "shameher.com"})})
    with pytest.raises(ZoneScopeError, match=r"not 'loremfile\.dev'"):
        client.verify_zone()
    assert client.verified_hostname is None
    with pytest.raises(ZoneScopeError):
        client.put(f"/zones/{OUR_ZONE}/settings/ssl", {"value": "strict"})


def test_a_zone_that_cannot_be_read_is_refused_rather_than_assumed() -> None:
    client = FakeClient({f"GET /zones/{OUR_ZONE}": Response(403, {"success": False, "errors": []})})
    with pytest.raises(ZoneScopeError, match="could not be confirmed"):
        client.verify_zone()


def test_a_write_to_another_zone_is_refused_even_after_verification() -> None:
    """Verification is not a blanket permit: each write re-checks its own target.

    This is the mis-templated-URL case — a correct zone verified, a wrong id in the path.
    """
    client = FakeClient()
    client.verify_zone()
    with pytest.raises(ZoneScopeError, match="targets zone"):
        client.put(f"/zones/{OTHER_ZONE}/rulesets/phases/http_request_transform/entrypoint", {})
    assert client.writes == []


def test_a_write_to_another_account_is_refused() -> None:
    client = FakeClient()
    client.verify_zone()
    with pytest.raises(ZoneScopeError, match="not ours"):
        client.post("/accounts/deadbeef/rulesets", {})


def test_reads_of_other_zones_are_allowed() -> None:
    """Only writes are scoped. An audit legitimately lists what else is on the account."""
    client = FakeClient()
    client.verify_zone()
    assert client.get(f"/zones/{OTHER_ZONE}").ok


def test_zone_scope_error_is_not_caught_by_the_general_handler() -> None:
    """`run` swallows CloudflareError per step; it must never swallow this one."""
    client = FakeClient({f"GET /zones/{OUR_ZONE}": ok({"name": "mcpreflex.dev"})})
    with pytest.raises(ZoneScopeError):
        apply_module.run(client)


# --- dry run ----------------------------------------------------------------


def test_dry_run_writes_nothing_and_names_the_zone() -> None:
    """A dry run that does not show which zone it resolved proves nothing."""
    client = FakeClient(dry_run=True)
    report = apply_module.run(client)
    assert client.writes == [], "dry run reached the transport"
    assert report.zone_id == OUR_ZONE
    assert report.hostname == "loremfile.dev"
    rendered = report.render()
    assert OUR_ZONE in rendered and "loremfile.dev" in rendered


def test_dry_run_still_reads_so_the_plan_is_real() -> None:
    client = FakeClient(dry_run=True)
    apply_module.run(client)
    assert any(method == "GET" for method, _ in client.calls)


# --- the steps --------------------------------------------------------------


def test_settings_already_correct_are_left_alone() -> None:
    desired = json.loads((apply_module.infra_dir() / "zone-settings.json").read_text())
    current = [{"id": k, "value": v, "editable": True} for k, v in desired.items()]
    client = FakeClient({f"GET /zones/{OUR_ZONE}/settings": ok(current)})
    client.verify_zone()
    report = apply_module.Report()
    apply_module.apply_zone_settings(client, report)
    assert client.writes == []
    assert {o.state for o in report.outcomes} == {"unchanged"}


def test_a_read_only_setting_is_skipped_not_failed() -> None:
    """polish and mirage are Pro features; a Free zone reports them non-editable."""
    current = [{"id": "polish", "value": "off", "editable": False}]
    client = FakeClient({f"GET /zones/{OUR_ZONE}/settings": ok(current)})
    client.verify_zone()
    report = apply_module.Report()
    apply_module.apply_zone_settings(client, report)
    assert [o.state for o in report.outcomes if o.resource == "setting:polish"] == ["skipped"]


def test_a_403_becomes_manual_with_a_dashboard_path_and_does_not_fail() -> None:
    """Permission names are still being confirmed (docs/08 §6); a refusal is not a crash."""
    client = FakeClient(
        {f"GET /zones/{OUR_ZONE}/bot_management": Response(403, {"success": False, "errors": []})}
    )
    client.verify_zone()
    report = apply_module.Report()
    apply_module.apply_bot_management(client, report)
    assert report.outcomes[0].state == "manual"
    assert "Bots" in report.outcomes[0].detail
    assert report.ok


def test_a_real_error_fails_the_run() -> None:
    client = FakeClient(
        {
            f"GET /zones/{OUR_ZONE}/settings": Response(
                500, {"success": False, "errors": [{"code": 1, "message": "boom"}]}
            )
        }
    )
    client.verify_zone()
    report = apply_module.Report()
    apply_module.apply_zone_settings(client, report)
    assert not report.ok


def test_every_written_phase_is_written_in_full() -> None:
    """A full PUT per phase — which is exactly why the scoping guard matters."""
    client = FakeClient()
    client.verify_zone()
    report = apply_module.Report()
    apply_module.apply_rulesets(client, report)
    written = {path for _, path, _ in client.writes}
    for phase in apply_module.WRITTEN_PHASES:
        assert f"/zones/{OUR_ZONE}/rulesets/phases/{phase}/entrypoint" in written


def test_the_managed_phase_is_verified_and_never_written() -> None:
    """Cloudflare owns that phase. Resolved 2026-09-09 against the live zone.

    The zone has no entry point there — `GET .../entrypoint` answers 10003 — and the
    managed ruleset appears in the zone's own ruleset list instead. Writing an entry
    point to add our `execute` rule would be writing a phase Cloudflare deploys into.
    """
    client = FakeClient(
        {
            f"GET /zones/{OUR_ZONE}/rulesets": ok(
                [
                    {
                        "id": "77454fe2d30c4220b5701f6fdfb893ba",
                        "name": apply_module.FREE_MANAGED_RULESET_NAME,
                        "kind": "managed",
                        "phase": apply_module.MANAGED_PHASE,
                    }
                ]
            )
        }
    )
    client.verify_zone()
    report = apply_module.Report()
    apply_module.apply_rulesets(client, report)

    assert not any(apply_module.MANAGED_PHASE in path for _, path, _ in client.writes)
    outcome = next(o for o in report.outcomes if o.resource == apply_module.MANAGED_PHASE)
    assert outcome.state == "skipped"
    assert "77454fe2d30c4220b5701f6fdfb893ba" in outcome.detail


def test_a_zone_without_the_managed_ruleset_is_a_finding() -> None:
    """If Free zones stop receiving it, that is a security assumption gone stale."""
    client = FakeClient({f"GET /zones/{OUR_ZONE}/rulesets": ok([])})
    client.verify_zone()
    report = apply_module.Report()
    apply_module.verify_managed_ruleset(client, report)
    assert report.outcomes[0].state == "failed"
    assert not report.ok


def test_the_managed_ruleset_is_never_looked_up_at_account_scope() -> None:
    """T1 is a zone token; listing account rulesets would mean widening it."""
    client = FakeClient()
    client.verify_zone()
    report = apply_module.Report()
    apply_module.apply_rulesets(client, report)
    assert not any(path.startswith("/accounts/") for _, path in client.calls), (
        "the managed-ruleset check must stay zone-scoped"
    )


def test_dns_never_deletes_and_only_adds_what_is_missing() -> None:
    """Email Routing owns MX and SPF; apply must not touch them."""
    existing = [
        {"type": "TXT", "name": "_dmarc.loremfile.dev"},
        {"type": "MX", "name": "loremfile.dev"},
    ]
    client = FakeClient({f"GET /zones/{OUR_ZONE}/dns_records": ok(existing)})
    client.verify_zone()
    report = apply_module.Report()
    apply_module.apply_dns(client, report)
    assert all(method != "DELETE" for method, _, _ in client.writes)
    created = [payload for method, path, payload in client.writes if method == "POST"]
    assert [c["type"] for c in created] == ["CNAME"], "only the missing www record"
