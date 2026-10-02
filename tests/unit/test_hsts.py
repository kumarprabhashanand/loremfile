"""HSTS: the zone's `security_header` setting, how apply and audit converge it, and the
header verify-live reads off production (docs/08 §3).

The setting is the first nested one in `zone-settings.json`. Cloudflare's object also holds
`nosniff`, which the desired state does not declare; these tests pin that an undeclared
field is neither written nor reported as drift.
"""

from __future__ import annotations

from typing import Any

from loremfile.config import SITE_HOST
from loremfile.infra import apply as apply_module
from loremfile.infra import audit, verify_live
from loremfile.infra.audit import DRIFT, OK, AuditReport
from loremfile.infra.cloudflare_api import Client, Response
from loremfile.infra.verify_live import Status

ZONE = "0123456789abcdef0123456789abcdef"
DESIRED = apply_module.load_desired("zone-settings.json")["security_header"]
DISABLED = {
    "strict_transport_security": {
        "enabled": False,
        "max_age": 0,
        "include_subdomains": False,
        "preload": False,
        "nosniff": True,
    }
}


def with_nosniff(nosniff: bool) -> dict[str, Any]:
    return {
        "strict_transport_security": {**DESIRED["strict_transport_security"], "nosniff": nosniff}
    }


def zone_with(value: Any) -> list[dict[str, Any]]:
    """Every committed setting as desired, except `security_header`, which is `value`."""
    return [
        {"id": key, "value": value if key == "security_header" else wanted, "editable": True}
        for key, wanted in apply_module.load_desired("zone-settings.json").items()
    ]


class Recording(Client):
    """A zone answering from `settings`, recording every write; never a socket."""

    def __init__(self, settings: list[dict[str, Any]]) -> None:
        super().__init__(token="not-a-token", zone_id=ZONE, account_id="a")  # noqa: S106
        self.settings = settings
        self.writes: list[tuple[str, str, dict[str, Any] | None]] = []

    def _send(self, method: str, path: str, payload: dict[str, Any] | None) -> Response:
        if method != "GET":
            self.writes.append((method, path, payload))
            return Response(200, {"success": True, "result": {}})
        if path == f"/zones/{ZONE}":
            return Response(200, {"success": True, "result": {"name": SITE_HOST}})
        return Response(200, {"success": True, "result": self.settings})


class ReadOnly:
    """What audit asks of a zone: one GET."""

    zone_id = ZONE

    def __init__(self, settings: list[dict[str, Any]]) -> None:
        self.settings = settings

    def get(self, _path: str) -> Response:
        return Response(200, {"success": True, "result": self.settings, "errors": []})


def applied(value: Any) -> Recording:
    client = Recording(zone_with(value))
    client.verify_zone()
    apply_module.apply_zone_settings(client, apply_module.Report())
    return client


def audited(value: Any) -> list[Any]:
    report = AuditReport()
    audit.audit_zone_settings(ReadOnly(zone_with(value)), report)  # type: ignore[arg-type]
    return [f for f in report.findings if f.resource == "setting:security_header"]


# --- the desired state -------------------------------------------------------------------


def test_one_year_subdomains_and_never_preload() -> None:
    hsts = DESIRED["strict_transport_security"]
    assert hsts == {
        "enabled": True,
        "max_age": 31_536_000,
        "include_subdomains": True,
        "preload": False,
    }
    assert "nosniff" not in hsts, "undeclared on purpose: the zone keeps its own value"


def test_verify_live_expects_the_committed_max_age() -> None:
    assert DESIRED["strict_transport_security"]["max_age"] == verify_live.HSTS_MAX_AGE


# --- converging a nested setting ---------------------------------------------------------


def test_declared_fields_are_laid_over_and_undeclared_ones_kept() -> None:
    assert apply_module.converged(DISABLED, DESIRED) == with_nosniff(True)


def test_a_scalar_setting_is_simply_the_desired_value() -> None:
    assert apply_module.converged("off", "on") == "on"
    assert apply_module.converged(None, {"a": 1}) == {"a": 1}


def test_apply_writes_the_declared_fields_and_keeps_nosniff() -> None:
    [(method, path, payload)] = applied(DISABLED).writes
    assert (method, path) == ("PATCH", f"/zones/{ZONE}/settings/security_header")
    assert payload == {"value": with_nosniff(True)}, "an undeclared field was overwritten"


def test_apply_leaves_a_converged_setting_alone_whatever_nosniff_is() -> None:
    """The control for the test above: undeclared fields are never a reason to write."""
    for nosniff in (True, False):
        assert applied(with_nosniff(nosniff)).writes == [], nosniff


def test_audit_reads_disabled_hsts_as_drift() -> None:
    [finding] = audited(DISABLED)
    assert finding.state == DRIFT
    assert "'enabled': False" in finding.detail


def test_audit_does_not_read_an_undeclared_field_as_drift() -> None:
    for nosniff in (True, False):
        assert [f.state for f in audited(with_nosniff(nosniff))] == [OK], nosniff


# --- the header, as production sends it --------------------------------------------------


def served(value: str | None) -> verify_live.Response:
    headers = {"strict-transport-security": value} if value is not None else {}
    return verify_live.Response(status=200, headers=headers)


def test_the_header_the_setting_produces_passes() -> None:
    finding = verify_live.check_hsts("/", served("max-age=31536000; includeSubDomains"))
    assert finding.status is Status.OK


def test_spacing_and_case_are_not_failures() -> None:
    finding = verify_live.check_hsts("/", served("max-age=31536000;includesubdomains"))
    assert finding.status is Status.OK


def test_a_missing_header_is_reported() -> None:
    assert verify_live.check_hsts("/", served(None)).status is Status.HEADER_MISSING


def test_each_wrong_directive_is_reported_by_name() -> None:
    cases = {
        "max-age=86400; includeSubDomains": "max-age",
        "max-age=31536000": "includeSubDomains",
        "max-age=31536000; includeSubDomains; preload": "preload",
    }
    for value, named in cases.items():
        finding = verify_live.check_hsts("/", served(value))
        assert finding.status is Status.HEADER_VALUE, value
        assert named in finding.detail, (value, finding.detail)
