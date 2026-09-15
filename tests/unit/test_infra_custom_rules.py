"""WAF custom rules are written one at a time, and only ours (ADR-030).

`http_request_firewall_custom` is the phase an incident adds rules to from the dashboard
(docs/11 §7.4). A PUT of its entry point removes every rule the request does not carry, so
ADR-008's pattern would delete an incident's rule on the next apply. These tests pin the
exception: rules whose ref starts with `loremfile_` are compared by ref and written by id,
every other rule is a warning and is never deleted, and the phase is never PUT.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

import pytest

from loremfile.infra import apply as apply_module
from loremfile.infra.apply import CUSTOM_PHASE, CUSTOM_REF_PREFIX, Report, apply_custom_rules
from loremfile.infra.audit import DRIFT, OK, UNREADABLE, AuditReport, audit_custom_rules
from loremfile.infra.cloudflare_api import NEVER_PUT_PHASES, Client, PhaseWriteRefused, Response

ZONE = "872580067ef0889f0b978acde39ea205"
ACCOUNT = "705c5f1733982ab6df37f715f1bafe56"
RULESET = "5ca1ab1e5ca1ab1e5ca1ab1e5ca1ab1e"
ENTRY = f"/zones/{ZONE}/rulesets/phases/{CUSTOM_PHASE}/entrypoint"
RULES = f"/zones/{ZONE}/rulesets/{RULESET}/rules"
NOT_A_TOKEN = "fake"  # noqa: S105


def ok(result: Any) -> Response:
    return Response(200, {"success": True, "result": result})


#: What the zone answered for the managed phase (docs/08 §5.6): no entry point, code 10003.
NO_ENTRY = Response(
    404,
    {
        "success": False,
        "result": None,
        "errors": [{"code": 10003, "message": "could not find entrypoint ruleset"}],
    },
)


class Zone(Client):
    """Answers the entry-point GET from a canned response; records every write it is sent."""

    def __init__(self, entry: Response, **kwargs: Any) -> None:
        super().__init__(token=NOT_A_TOKEN, zone_id=ZONE, account_id=ACCOUNT, **kwargs)
        self.entry = entry
        self.writes: list[tuple[str, str, dict[str, Any] | None]] = []

    def _send(self, method: str, path: str, payload: dict[str, Any] | None) -> Response:
        if path == f"/zones/{ZONE}":
            return ok({"name": "loremfile.dev"})
        if method == "GET" and path == ENTRY:
            return self.entry
        self.writes.append((method, path, payload))
        return ok({"id": RULESET, "rules": []})


def verified(entry: Response, **kwargs: Any) -> Zone:
    zone = Zone(entry, **kwargs)
    zone.verify_zone()
    return zone


def committed() -> list[dict[str, Any]]:
    return apply_module.custom_rules_desired()


def deployed(*rules: dict[str, Any]) -> Response:
    """The entry point as Cloudflare returns it: our fields plus the ones it assigns."""
    stored = [
        {**copy.deepcopy(rule), "id": f"rule{index}", "version": "1", "last_updated": "2026-09-15"}
        for index, rule in enumerate(rules)
    ]
    return ok({"id": RULESET, "phase": CUSTOM_PHASE, "rules": stored})


def incident_rule() -> dict[str, Any]:
    """Shaped as docs/11 §7.4 step 3: added in the dashboard, with no ref of ours."""
    return {
        "description": "incident: block one ASN",
        "expression": "ip.src.asnum eq 64496",
        "action": "block",
        "enabled": True,
    }


def states(report: Report) -> dict[str, str]:
    return {o.resource: o.state for o in report.outcomes}


# --- the committed file ------------------------------------------------------------


def test_the_committed_file_has_rules_and_every_ref_is_ours() -> None:
    """Empty-set control first: with no committed rule, every test below is vacuous."""
    rules = committed()
    assert rules
    for rule in rules:
        assert rule["ref"].startswith(CUSTOM_REF_PREFIX), rule["ref"]


def test_the_phase_fits_the_free_plan() -> None:
    """Cloudflare's availability table: Free has 5 custom rules, no regex, no Log action."""
    rules = committed()
    assert len(rules) <= 5
    for rule in rules:
        assert " matches " not in rule["expression"]
        assert rule["action"] != "log"


def test_the_phase_is_outside_adr_008() -> None:
    assert CUSTOM_PHASE in NEVER_PUT_PHASES
    assert CUSTOM_PHASE not in apply_module.WRITTEN_PHASES
    assert CUSTOM_PHASE in apply_module.PHASES


# --- the refusal ----------------------------------------------------------------------


def test_a_put_of_the_entry_point_is_refused_before_it_is_sent() -> None:
    zone = verified(NO_ENTRY)
    with pytest.raises(PhaseWriteRefused, match="ADR-030"):
        zone.put(ENTRY, {"rules": committed()})
    assert zone.writes == []
    # Negative control: the same client still PUTs a phase ADR-008 owns.
    transform = f"/zones/{ZONE}/rulesets/phases/http_request_transform/entrypoint"
    zone.put(transform, {"rules": []})
    assert zone.writes == [("PUT", transform, {"rules": []})]


def test_the_refusal_holds_in_a_dry_run() -> None:
    """A dry run no-ops writes after the scope checks; this one must still raise."""
    zone = verified(NO_ENTRY, dry_run=True)
    with pytest.raises(PhaseWriteRefused):
        zone.put(ENTRY, {"rules": []})


# --- apply ---------------------------------------------------------------------------


def test_a_zone_that_already_matches_is_not_written() -> None:
    zone = verified(deployed(*committed()))
    report = Report()
    apply_custom_rules(zone, report)
    assert zone.writes == []
    assert list(states(report).values()) == ["unchanged"] * len(committed())


@pytest.mark.parametrize(
    "entry",
    [NO_ENTRY, Response(404, {"success": False, "errors": []})],
    ids=["10003", "bare-404"],
)
def test_no_entry_point_is_created_with_our_rules(entry: Response) -> None:
    zone = verified(entry)
    report = Report()
    apply_custom_rules(zone, report)
    create = {"name": "default", "kind": "zone", "phase": CUSTOM_PHASE, "rules": committed()}
    assert zone.writes == [("POST", f"/zones/{ZONE}/rulesets", create)]
    assert set(states(report).values()) == {"updated"}


def test_one_changed_rule_is_patched_by_id_with_the_whole_rule() -> None:
    live = copy.deepcopy(committed())
    live[0]["expression"] += " and true"
    zone = verified(deployed(*live))
    report = Report()
    apply_custom_rules(zone, report)
    assert zone.writes == [("PATCH", f"{RULES}/rule0", committed()[0])]
    assert report.outcomes[0].state == "updated"


def test_a_missing_rule_is_added_and_an_incident_rule_is_left_alone() -> None:
    zone = verified(deployed(incident_rule()))
    report = Report()
    apply_custom_rules(zone, report)
    assert zone.writes == [("POST", RULES, rule) for rule in committed()]
    assert states(report)[f"{CUSTOM_PHASE}:rule0"] == "warning"
    assert report.ok, "a rule that is not ours is a warning, not a failure"


def test_ours_no_longer_committed_is_deleted_but_never_anyone_elses() -> None:
    """The negative control for "never deleted": the delete path exists and fires for our
    prefix, so leaving the incident rule alone is a decision, not a missing feature."""
    stale = {"ref": f"{CUSTOM_REF_PREFIX}retired", "expression": "true", "action": "block"}
    zone = verified(deployed(*committed(), stale, incident_rule()))
    report = Report()
    apply_custom_rules(zone, report)
    ours = len(committed())
    assert zone.writes == [("DELETE", f"{RULES}/rule{ours}", None)]
    assert states(report)[f"{CUSTOM_PHASE}:rule{ours + 1}"] == "warning"


@pytest.mark.parametrize(("status", "state"), [(403, "manual"), (500, "failed")])
def test_an_entry_point_that_cannot_be_read_is_not_written(status: int, state: str) -> None:
    zone = verified(Response(status, {"success": False, "errors": [{"code": 1, "message": "x"}]}))
    report = Report()
    apply_custom_rules(zone, report)
    assert zone.writes == []
    assert states(report) == {CUSTOM_PHASE: state}


def test_a_dry_run_writes_nothing_and_still_plans() -> None:
    zone = verified(NO_ENTRY, dry_run=True)
    report = Report()
    apply_custom_rules(zone, report)
    assert zone.writes == []
    assert set(states(report).values()) == {"updated"}


def test_no_scenario_ever_sends_a_put() -> None:
    """The structural half: the writer never tries, so the refusal never has to fire."""
    changed = copy.deepcopy(committed())
    changed[0]["action"] = "managed_challenge"
    stale = {"ref": f"{CUSTOM_REF_PREFIX}retired", "expression": "true", "action": "block"}
    scenarios = [
        NO_ENTRY,
        deployed(),
        deployed(incident_rule()),
        deployed(*committed()),
        deployed(*changed),
        deployed(*committed(), stale),
    ]
    methods: set[str] = set()
    for entry in scenarios:
        zone = verified(entry)
        apply_custom_rules(zone, Report())
        assert [w for w in zone.writes if w[0] == "PUT"] == []
        methods |= {method for method, _path, _payload in zone.writes}
    # Empty-set control: across these scenarios it did write, with every verb it uses.
    assert methods == {"POST", "PATCH", "DELETE"}


def leaves(value: Any, path: tuple[Any, ...] = ()) -> Iterator[tuple[tuple[Any, ...], Any]]:
    if isinstance(value, dict):
        for key, inner in value.items():
            yield from leaves(inner, (*path, key))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            yield from leaves(inner, (*path, index))
    else:
        yield path, value


MUTATIONS = [
    (index, path, leaf) for index, rule in enumerate(committed()) for path, leaf in leaves(rule)
]


def test_the_mutation_set_reaches_every_declared_field() -> None:
    assert {path[0] for _index, path, _leaf in MUTATIONS} >= {"ref", "expression", "action"}


@pytest.mark.parametrize(("index", "path", "leaf"), MUTATIONS)
def test_a_change_to_any_declared_leaf_is_written(
    index: int, path: tuple[Any, ...], leaf: Any
) -> None:
    """The dangerous direction is a false "equal": a committed change that never lands."""
    live = copy.deepcopy(committed())
    target: Any = live[index]
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = (not leaf) if isinstance(leaf, bool) else f"{leaf}-changed"
    zone = verified(deployed(*live))
    apply_custom_rules(zone, Report())
    assert zone.writes, f"rule {index} {path}: compared equal"


# --- audit ---------------------------------------------------------------------------


def audited(entry: Response) -> AuditReport:
    zone = Zone(entry, read_only=True)
    zone.verify_zone()
    report = AuditReport()
    audit_custom_rules(zone, report)
    return report


def test_audit_a_matching_zone_is_ok() -> None:
    report = audited(deployed(*committed()))
    assert [f.state for f in report.findings] == [OK] * len(committed())


def test_audit_an_incident_rule_is_a_warning_never_drift() -> None:
    report = audited(deployed(*committed(), incident_rule()))
    assert report.drifted == []
    assert report.ok
    assert [f.resource for f in report.warnings] == [f"{CUSTOM_PHASE}:rule{len(committed())}"]


def test_audit_missing_changed_and_stale_rules_are_drift() -> None:
    """Negative control for the test above: the same audit does report drift."""
    assert [f.state for f in audited(deployed()).findings] == [DRIFT] * len(committed())

    live = copy.deepcopy(committed())
    live[0]["expression"] += " and true"
    assert audited(deployed(*live)).findings[0].state == DRIFT

    stale = {"ref": f"{CUSTOM_REF_PREFIX}retired", "expression": "true", "action": "block"}
    assert [f.resource for f in audited(deployed(*committed(), stale)).drifted] == [
        f"{CUSTOM_PHASE}:{CUSTOM_REF_PREFIX}retired"
    ]


def test_audit_no_entry_point_is_drift_for_every_rule_of_ours() -> None:
    report = audited(NO_ENTRY)
    assert [f.state for f in report.findings] == [DRIFT] * len(committed())


def test_audit_a_refused_read_is_unreadable_not_drift() -> None:
    report = audited(Response(403, {"success": False, "errors": []}))
    assert [f.state for f in report.findings] == [UNREADABLE]
    assert report.ok
