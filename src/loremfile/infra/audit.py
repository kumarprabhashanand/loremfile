"""Compare the zone against `infra/` and report differences (docs/09 §3.4).

**`apply` reports the write. `audit` reports the state.** They are not the same function
with a flag, and the distinction is the whole reason this module exists.

`apply` writes ruleset entry points with an unconditional full `PUT` — deliberately, so
that a phase converges in one call regardless of what was there — and therefore reports
`updated` on every run whether or not anything differed. Six resources do this today: the
five written phases and the tiered-cache topology. An audit that reused those outcomes
would open an `infra-drift` issue every single week, and **a label that fires every run
stops meaning anything.** That is the failure already avoided for `fonts`/`speed_brain`
(`docs/08` §8) and for `expected_drift` (`docs/06` §8); this is the third place it would
have appeared.

So every check here **reads**, and the client is constructed read-only: a write raises
`ReadOnlyError` rather than silently converging the drift the audit was sent to report.
`audit.yml` runs with T1 because Cloudflare tokens cannot be split read/write per call, so
"the audit never writes" needs to be enforced by something other than a comment.

**What "the same" means for a rule.** Cloudflare adds `id`, `version`, `ref` and
`last_updated` to every rule it stores, and fills defaults for fields we did not send.
Comparing whole objects would report drift on every rule forever, so the comparison is
over **the fields the committed rule actually declares**, in order. The consequence is
stated rather than hidden: a field Cloudflare added on its own is invisible here. We own
what we declare; Cloudflare owns the rest, and a rule of ours that changed shape shows up
because *our* fields are what moved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from loremfile.config import SITE_HOST
from loremfile.infra.apply import (
    FALLBACKS,
    FREE_MANAGED_RULESET_NAME,
    HTTP_FORBIDDEN,
    HTTP_NOT_FOUND,
    MANAGED_PHASE,
    WRITTEN_PHASES,
    load_desired,
    managed_ruleset_deployed,
)
from loremfile.infra.cloudflare_api import Client, CloudflareError, Response

#: Cloudflare assigns these; they are not ours to compare.
SERVER_ASSIGNED = frozenset({"id", "version", "ref", "last_updated"})

#: One outcome per resource. `drift` is the only one that opens an issue.
OK = "ok"
DRIFT = "drift"
UNREADABLE = "unreadable"


@dataclass
class Finding:
    resource: str
    state: str
    detail: str = ""


@dataclass
class AuditReport:
    zone_id: str = ""
    hostname: str = ""
    findings: list[Finding] = field(default_factory=list)

    def add(self, resource: str, state: str, detail: str = "") -> None:
        self.findings.append(Finding(resource, state, detail))

    @property
    def drifted(self) -> list[Finding]:
        return [f for f in self.findings if f.state == DRIFT]

    @property
    def unreadable(self) -> list[Finding]:
        return [f for f in self.findings if f.state == UNREADABLE]

    @property
    def ok(self) -> bool:
        """Unreadable is a **warning**, not a failure (docs/09 §3.4).

        A permission that cannot read a setting says nothing about whether the setting is
        right, and failing on it would make the audit useless on the days it matters.
        """
        return not self.drifted

    def render(self) -> str:
        width = max((len(f.resource) for f in self.findings), default=8)
        lines = [f"zone {self.zone_id} ({self.hostname})", ""]
        lines += [
            f"  {f.resource.ljust(width)}  {f.state:<10} {f.detail}".rstrip() for f in self.findings
        ]
        if self.unreadable:
            lines += ["", "Could not be read (warning, not drift):"]
            lines += [f"  {f.resource}: {f.detail}" for f in self.unreadable]
        return "\n".join(lines)


def _unreadable(response: Response) -> bool:
    return response.status in {HTTP_FORBIDDEN, HTTP_NOT_FOUND}


def declared_fields(rule: dict[str, Any]) -> dict[str, Any]:
    """The rule as we declared it: server-assigned keys dropped."""
    return {k: v for k, v in rule.items() if k not in SERVER_ASSIGNED}


def compare_rules(desired: list[dict[str, Any]], deployed: list[dict[str, Any]]) -> list[str]:
    """Differences between committed rules and deployed ones, in order.

    Order is part of a ruleset's meaning — rules are evaluated top to bottom — so this
    compares position by position rather than as sets.
    """
    differences: list[str] = []
    if len(desired) != len(deployed):
        differences.append(f"{len(deployed)} rule(s) deployed, {len(desired)} committed")
    for index, want in enumerate(desired):
        if index >= len(deployed):
            differences.append(f"[{index}] missing: {want.get('description', '?')!r}")
            continue
        have = deployed[index]
        for key, value in declared_fields(want).items():
            if have.get(key) != value:
                differences.append(
                    f"[{index}] {want.get('description', '?')!r}: {key} is "
                    f"{json.dumps(have.get(key))} not {json.dumps(value)}"
                )
    for index in range(len(desired), len(deployed)):
        extra = deployed[index]
        differences.append(f"[{index}] extra rule deployed: {extra.get('description', '?')!r}")
    return differences


def audit_rulesets(client: Client, report: AuditReport) -> None:
    """The six-resource problem: read each phase and compare content."""
    for phase in WRITTEN_PHASES:
        path = f"/zones/{client.zone_id}/rulesets/phases/{phase}/entrypoint"
        response = client.get(path)
        if _unreadable(response):
            report.add(phase, UNREADABLE, FALLBACKS[phase])
            continue
        if not response.ok:
            report.add(phase, UNREADABLE, response.errors)
            continue
        deployed = list((response.result or {}).get("rules") or [])
        desired = list(load_desired(f"rulesets/{phase}.json")["rules"])
        differences = compare_rules(desired, deployed)
        if differences:
            report.add(phase, DRIFT, "; ".join(differences))
        else:
            report.add(phase, OK, f"{len(desired)} rule(s) match")

    deployed_managed = managed_ruleset_deployed(client)
    if deployed_managed is None:
        report.add(MANAGED_PHASE, DRIFT, "no managed ruleset is deployed in this phase")
    elif deployed_managed.get("name") != FREE_MANAGED_RULESET_NAME:
        report.add(MANAGED_PHASE, DRIFT, f"deployed ruleset is {deployed_managed.get('name')!r}")
    else:
        report.add(MANAGED_PHASE, OK, FREE_MANAGED_RULESET_NAME)


def audit_zone_settings(client: Client, report: AuditReport) -> None:
    desired = load_desired("zone-settings.json")
    current = client.get(f"/zones/{client.zone_id}/settings")
    if not current.ok:
        report.add("zone-settings", UNREADABLE, current.errors)
        return
    by_id = {item["id"]: item for item in (current.result or [])}
    for key, value in desired.items():
        found = by_id.get(key)
        if found is None:
            report.add(f"setting:{key}", UNREADABLE, "not offered on this plan")
        elif found.get("value") != value:
            report.add(f"setting:{key}", DRIFT, f"is {found.get('value')!r}, want {value!r}")
        else:
            report.add(f"setting:{key}", OK)


def audit_bot_management(client: Client, report: AuditReport) -> None:
    desired = load_desired("bot-management.json")
    current = client.get(f"/zones/{client.zone_id}/bot_management")
    if _unreadable(current) or not current.ok:
        report.add("bot-management", UNREADABLE, FALLBACKS["bot-management"])
        return
    found = current.result or {}
    wrong = {k: found.get(k) for k, v in desired.items() if found.get(k) != v}
    if wrong:
        report.add("bot-management", DRIFT, json.dumps(wrong, sort_keys=True))
    else:
        report.add("bot-management", OK)


def audit_dnssec(client: Client, report: AuditReport) -> None:
    current = client.get(f"/zones/{client.zone_id}/dnssec")
    if _unreadable(current) or not current.ok:
        report.add("dnssec", UNREADABLE, FALLBACKS["dnssec"])
        return
    status = (current.result or {}).get("status")
    report.add("dnssec", OK if status == "active" else DRIFT, str(status))


def audit_dns(client: Client, report: AuditReport) -> None:
    """Only the records `infra/dns.json` claims. Email Routing owns MX and SPF."""
    desired = load_desired("dns.json")["records"]
    listing = client.get(f"/zones/{client.zone_id}/dns_records?per_page=100")
    if not listing.ok:
        report.add("dns", UNREADABLE, listing.errors)
        return
    existing = {(r["type"], r["name"]): r for r in (listing.result or [])}
    for record in desired:
        fqdn = (
            record["name"]
            if record["name"].endswith(SITE_HOST)
            else f"{record['name']}.{SITE_HOST}"
        )
        found = existing.get((record["type"], fqdn))
        name = f"dns:{record['type']} {record['name']}"
        if found is None:
            report.add(name, DRIFT, "absent")
        elif found.get("content") != record.get("content"):
            report.add(name, DRIFT, f"content is {found.get('content')!r}")
        else:
            report.add(name, OK)


def audit_tiered_cache(client: Client, report: AuditReport) -> None:
    """Read the topology. `apply` PATCHes it unconditionally and always says `updated`."""
    path = f"/zones/{client.zone_id}/cache/tiered_cache_smart_topology_enable"
    current = client.get(path)
    if _unreadable(current) or not current.ok:
        report.add("tiered-cache", UNREADABLE, FALLBACKS["tiered-cache"])
        return
    value = (current.result or {}).get("value")
    report.add("tiered-cache", OK if value == "on" else DRIFT, f"smart topology {value!r}")


def audit_url_normalization(client: Client, report: AuditReport) -> None:
    path = f"/zones/{client.zone_id}/url_normalization"
    current = client.get(path)
    if _unreadable(current) or not current.ok:
        report.add("url-normalization", UNREADABLE, FALLBACKS["url-normalization"])
        return
    found = current.result or {}
    if found.get("type") == "cloudflare" and found.get("scope") == "incoming":
        report.add("url-normalization", OK)
    else:
        report.add("url-normalization", DRIFT, json.dumps(found, sort_keys=True))


CHECKS = (
    audit_zone_settings,
    audit_bot_management,
    audit_dnssec,
    audit_dns,
    audit_rulesets,
    audit_tiered_cache,
    audit_url_normalization,
)


def run(client: Client) -> AuditReport:
    """Read the zone and report what differs. Writes nothing, and cannot.

    The zone is still verified first — not because anything is about to be written, but
    because an audit that read a *different* zone would report a clean bill of health for
    the wrong zone, which is worse than failing.
    """
    report = AuditReport(zone_id=client.zone_id)
    report.hostname = client.verify_zone(SITE_HOST)
    for check in CHECKS:
        try:
            check(client, report)
        except CloudflareError as exc:
            report.add(check.__name__.removeprefix("audit_"), UNREADABLE, str(exc))
    return report
