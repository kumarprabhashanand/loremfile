"""Compare the zone against `infra/` and report differences (docs/09 §3.4).

**`apply` reports the write. `audit` reports the state.** They are not the same function
with a flag, and the distinction is the whole reason this module exists.

`apply` reports what it wrote — or, in a dry run, would write — and exits 0 on a
difference. Until 2026-09-15 it wrote the five ruleset phases and the tiered-cache topology
unconditionally and said `updated` for all six on every run; an audit that had reused those
outcomes would have opened an `infra-drift` issue every week, and **a label that fires every
run stops meaning anything** — the failure avoided for `fonts`/`speed_brain` (`docs/08` §8)
and for `expected_drift` (`docs/06` §8). `apply` compares before it writes now, with the
function below, but the audit still reports from its own reads, never from `apply`'s outcomes.

So every check here **reads**, and the client is constructed read-only: a write raises
`ReadOnlyError` rather than silently converging the drift the audit was sent to report.
`audit.yml` runs with T1 because Cloudflare tokens cannot be split read/write per call, so
"the audit never writes" needs to be enforced by something other than a comment.

**What "the same" means for a rule.** Cloudflare adds `id`, `version` and `last_updated`
to every rule it stores, and fills defaults for fields we did not send. (`ref` is ours: the
committed files declare it and the live zone preserves it, so it is compared.) The comparison
lives in `apply.compare_rules`, shared with `apply`, which writes only on a difference.
Comparing whole objects would report drift on every rule forever, so the comparison is
over **the fields the committed rule actually declares**, in order. The consequence is
stated rather than hidden: a field Cloudflare added on its own is invisible here. We own
what we declare; Cloudflare owns the rest, and a rule of ours that changed shape shows up
because *our* fields are what moved.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from typing import Any

from loremfile.config import SITE_HOST
from loremfile.infra import locks
from loremfile.infra.apply import (
    CUSTOM_PHASE,
    CUSTOM_REF_PREFIX,
    FALLBACKS,
    FREE_MANAGED_RULESET_NAME,
    HTTP_FORBIDDEN,
    HTTP_NOT_FOUND,
    MANAGED_PHASE,
    WRITTEN_PHASES,
    compare_rules,
    custom_rules_desired,
    dns_content,
    is_ours,
    load_desired,
    managed_ruleset_deployed,
    no_entry_point,
)
from loremfile.infra.cloudflare_api import Client, CloudflareError, Response
from loremfile.infra.r2 import bucket_name

#: One outcome per resource. `drift` is the only one that opens an issue.
OK = "ok"
DRIFT = "drift"
UNREADABLE = "unreadable"
#: A custom rule that is not ours (ADR-030): reported, never drift, never deleted.
WARNING = "warning"


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
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.state == WARNING]

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
        if self.warnings:
            lines += ["", "Not ours, left in place (warning, not drift):"]
            lines += [f"  {f.resource}: {f.detail}" for f in self.warnings]
        return "\n".join(lines)


def _unreadable(response: Response) -> bool:
    return response.status in {HTTP_FORBIDDEN, HTTP_NOT_FOUND}


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


def audit_custom_rules(client: Client, report: AuditReport) -> None:
    """Our custom rules, by ref. Anyone else's are a warning, never drift (ADR-030)."""
    desired = custom_rules_desired()
    response = client.get(f"/zones/{client.zone_id}/rulesets/phases/{CUSTOM_PHASE}/entrypoint")
    if no_entry_point(response):
        for want in desired:
            resource = f"{CUSTOM_PHASE}:{want['ref']}"
            report.add(resource, DRIFT, "missing: the phase has no entry point")
        if not desired:
            report.add(CUSTOM_PHASE, OK, "no entry point, and no rule of ours")
        return
    ruleset = response.result if response.ok else None
    if not isinstance(ruleset, dict):
        forbidden = response.status == HTTP_FORBIDDEN
        report.add(
            CUSTOM_PHASE, UNREADABLE, FALLBACKS[CUSTOM_PHASE] if forbidden else response.errors
        )
        return

    ours: dict[str, dict[str, Any]] = {}
    for rule in ruleset.get("rules") or []:
        if is_ours(rule):
            ours[rule["ref"]] = rule
        else:
            name = rule.get("ref") or rule.get("id", "?")
            report.add(
                f"{CUSTOM_PHASE}:{name}",
                WARNING,
                "not ours: never deleted; port it into infra/ if it should stay (docs/11 §7.4)",
            )
    for want in desired:
        resource = f"{CUSTOM_PHASE}:{want['ref']}"
        have = ours.pop(want["ref"], None)
        if have is None:
            report.add(resource, DRIFT, "missing")
        elif differences := compare_rules([want], [have]):
            report.add(resource, DRIFT, "; ".join(differences))
        else:
            report.add(resource, OK, "matches")
    for ref in ours:
        detail = f"deployed with the {CUSTOM_REF_PREFIX} prefix but not committed"
        report.add(f"{CUSTOM_PHASE}:{ref}", DRIFT, detail)


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
        elif dns_content(record["type"], found.get("content")) != dns_content(
            record["type"], record.get("content")
        ):
            report.add(name, DRIFT, f"content is {found.get('content')!r}")
        else:
            report.add(name, OK)


def audit_tiered_cache(client: Client, report: AuditReport) -> None:
    """Read the topology and compare it; never borrowed from `apply`'s outcome."""
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


def audit_bucket_locks(client: Client, report: AuditReport) -> None:
    """Compare the lock rules R2 actually holds with `infra/r2-locks.json`.

    Until now nothing read the applied rules: the deploy gate reads the committed file,
    while four places — two docstrings, `08` §2 and the deploy's gate comment — described
    a comparison that did not exist. The bucket is the storage-layer
    half of immutability (ADR-023), so a rule silently removed, disabled or narrowed is
    drift, not a warning — a published prefix would be overwritable by a leaked T2 with
    nothing anywhere saying so.

    Needs an account-scoped R2 read, which the zone token does not have and must not be
    given (`08` §6), so it uses `R2_READ_TOKEN`. No token, or a token the API refuses, is
    **unreadable** — never `ok`: an audit that could not look has learned nothing, and
    reporting that as clean is the failure this check was added to prevent.
    """
    token = os.environ.get("R2_READ_TOKEN", "")
    if not token:
        report.add("bucket-locks", UNREADABLE, FALLBACKS["bucket-locks"])
        return

    reader = replace(client, token=token, read_only=True)
    current = reader.get(f"/accounts/{client.account_id}/r2/buckets/{bucket_name()}/lock")
    if _unreadable(current) or not current.ok:
        report.add("bucket-locks", UNREADABLE, f"{FALLBACKS['bucket-locks']}: {current.errors}")
        return

    applied = {
        str(rule.get("prefix", "")): rule for rule in (current.result or {}).get("rules", [])
    }
    committed = {str(rule["prefix"]): rule for rule in locks.committed_rules()}

    differences = [
        *(
            f"{prefix}: applied to the bucket, not committed"
            for prefix in sorted(set(applied) - set(committed))
        ),
        *(
            f"{prefix}: committed, not applied to the bucket"
            for prefix in sorted(set(committed) - set(applied))
        ),
    ]
    for prefix in sorted(set(applied) & set(committed)):
        live, want = applied[prefix], committed[prefix]
        if live.get("enabled") is not want.get("enabled"):
            differences.append(
                f"{prefix}: enabled={live.get('enabled')}, committed {want.get('enabled')}"
            )
        live_type = (live.get("condition") or {}).get("type")
        want_type = (want.get("condition") or {}).get("type")
        if live_type != want_type:
            differences.append(f"{prefix}: condition {live_type!r}, committed {want_type!r}")

    detail = f"{len(applied)} applied, {len(committed)} committed"
    if differences:
        report.add("bucket-locks", DRIFT, f"{detail}; " + "; ".join(differences))
    else:
        report.add("bucket-locks", OK, f"all {len(committed)} rules match")


CHECKS = (
    audit_zone_settings,
    audit_bot_management,
    audit_dnssec,
    audit_dns,
    audit_rulesets,
    audit_custom_rules,
    audit_tiered_cache,
    audit_url_normalization,
    audit_bucket_locks,
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
