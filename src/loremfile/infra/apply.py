"""Apply `infra/` to Cloudflare (docs/08 §6). Runs only from `infra.yml`.

The eight steps are the spec's. What is not in the spec, and is the reason to read this
file before running it, is the order of the first two: **the zone is verified before any
step executes, and `--dry-run` prints the zone id and hostname it resolved.** Ruleset
entry points are written with a full PUT, so a request aimed at the wrong zone replaces
that zone's rules rather than adding to them, and this account holds two unrelated
production zones. `cloudflare_api.Client` refuses every write until `verify_zone`
succeeds; this module makes sure it is called first and that a human can see the answer.

A step whose endpoint returns 403 is reported as `manual` with the dashboard path from
docs/08 §2 rather than failing the run — the permission names are still being confirmed
(docs/08 §6's table). A step that fails for any other reason fails the run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loremfile import config
from loremfile.config import SITE_HOST
from loremfile.infra.cloudflare_api import (
    Client,
    CloudflareError,
    Response,
    ZoneScopeError,
)

#: Ruleset phases this project writes. No other phase is ever read or written: a full
#: PUT on a phase someone else configured would replace their rules with ours.
WRITTEN_PHASES = (
    "http_request_dynamic_redirect",
    "http_request_transform",
    "http_response_headers_transform",
    "http_request_cache_settings",
    "http_ratelimit",
)

#: Verified by GET, never written (docs/08 §5.6, resolved 2026-09-09). Cloudflare deploys
#: its managed ruleset into this phase itself; the zone has no entry point of its own, and
#: `GET .../phases/http_request_firewall_managed/entrypoint` answers `10003: could not
#: find entrypoint ruleset`. Creating one to add our `execute` rule would be writing a
#: phase Cloudflare owns, so apply confirms the managed ruleset is deployed and stops.
MANAGED_PHASE = "http_request_firewall_managed"

#: Every phase with a file in infra/rulesets/.
PHASES = (*WRITTEN_PHASES, MANAGED_PHASE)

#: docs/08 §6: the dashboard path to print when the API refuses a step.
FALLBACKS = {
    "zone-settings": "Speed / Security / Scrape Shield toggles",
    "bot-management": "Security → Bots (docs/08 §2 step 13)",
    "dnssec": "DNS → Settings → Enable DNSSEC",
    "dns": "DNS → Records",
    "http_request_dynamic_redirect": "Rules → Redirect Rules",
    "http_request_transform": "Rules → Transform Rules",
    "http_response_headers_transform": "Rules → Transform Rules",
    "http_request_cache_settings": "Caching → Cache Rules",
    "http_ratelimit": "Security → WAF → Rate limiting rules",
    "http_request_firewall_managed": "Security → WAF → Managed rules",
    "tiered-cache": "Caching → Tiered Cache → Smart Tiered Cache",
    "url-normalization": "Rules → Settings → Normalize incoming URLs",
}

#: The zone reports this name. docs/08 §5.6 had the words transposed ("Cloudflare Free
#: Managed Ruleset"), so a name match would never have succeeded — corrected 2026-09-09.
FREE_MANAGED_RULESET_NAME = "Cloudflare Managed Free Ruleset"

#: A refused permission is reported as `manual` with a dashboard path; a missing
#: endpoint means the API shape in docs/08 §6 is wrong and M2.3 has to record that.
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


@dataclass
class Outcome:
    resource: str
    state: str  # unchanged | updated | skipped | manual | failed
    detail: str = ""


@dataclass
class Report:
    zone_id: str = ""
    hostname: str = ""
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(o.state == "failed" for o in self.outcomes)

    def add(self, resource: str, state: str, detail: str = "") -> None:
        self.outcomes.append(Outcome(resource, state, detail))

    def render(self) -> str:
        width = max((len(o.resource) for o in self.outcomes), default=8)
        lines = [f"zone {self.zone_id} ({self.hostname})", ""]
        lines += [
            f"  {o.resource.ljust(width)}  {o.state:<9} {o.detail}".rstrip() for o in self.outcomes
        ]
        manual = [o for o in self.outcomes if o.state == "manual"]
        if manual:
            lines += ["", "Needs the dashboard:"]
            lines += [f"  {o.resource}: {o.detail}" for o in manual]
        return "\n".join(lines)


def infra_dir() -> Path:
    return config.repo_root() / "infra"


def _load(name: str) -> Any:  # noqa: ANN401 - each file has its own shape
    return json.loads((infra_dir() / name).read_text(encoding="utf-8"))


def _is_forbidden(response: Response) -> bool:
    return response.status == HTTP_FORBIDDEN


def apply_zone_settings(client: Client, report: Report) -> None:
    desired = _load("zone-settings.json")
    current = client.get(f"/zones/{client.zone_id}/settings")
    if not current.ok:
        report.add("zone-settings", "failed", current.errors)
        return
    by_id = {item["id"]: item for item in (current.result or [])}
    for key, value in desired.items():
        found = by_id.get(key)
        if found is None:
            report.add(f"setting:{key}", "skipped", "not offered on this plan")
            continue
        if not found.get("editable", True):
            # Pro-only settings (polish, mirage): audit only complains if not off.
            report.add(f"setting:{key}", "skipped", f"read-only, is {found.get('value')!r}")
            continue
        if found.get("value") == value:
            report.add(f"setting:{key}", "unchanged")
            continue
        response = client.patch(f"/zones/{client.zone_id}/settings/{key}", {"value": value})
        if response.ok:
            report.add(f"setting:{key}", "updated", f"{found.get('value')!r} → {value!r}")
        elif _is_forbidden(response):
            report.add(f"setting:{key}", "manual", FALLBACKS["zone-settings"])
        else:
            report.add(f"setting:{key}", "failed", response.errors)


def apply_bot_management(client: Client, report: Report) -> None:
    desired = _load("bot-management.json")
    current = client.get(f"/zones/{client.zone_id}/bot_management")
    if _is_forbidden(current):
        report.add("bot-management", "manual", FALLBACKS["bot-management"])
        return
    if current.ok and all((current.result or {}).get(k) == v for k, v in desired.items()):
        report.add("bot-management", "unchanged")
        return
    response = client.put(f"/zones/{client.zone_id}/bot_management", desired)
    if response.ok:
        report.add("bot-management", "updated")
    elif _is_forbidden(response):
        report.add("bot-management", "manual", FALLBACKS["bot-management"])
    else:
        report.add("bot-management", "failed", response.errors)


def apply_dnssec(client: Client, report: Report) -> None:
    current = client.get(f"/zones/{client.zone_id}/dnssec")
    if _is_forbidden(current):
        report.add("dnssec", "manual", FALLBACKS["dnssec"])
        return
    if current.ok and (current.result or {}).get("status") == "active":
        report.add("dnssec", "unchanged", "active")
        return
    response = client.patch(f"/zones/{client.zone_id}/dnssec", {"status": "active"})
    if response.ok:
        report.add("dnssec", "updated")
    elif _is_forbidden(response):
        report.add("dnssec", "manual", FALLBACKS["dnssec"])
    else:
        report.add("dnssec", "failed", response.errors)


def apply_dns(client: Client, report: Report) -> None:
    """Ensure the records we own. Never deletes: Email Routing owns MX and SPF."""
    desired = _load("dns.json")["records"]
    listing = client.get(f"/zones/{client.zone_id}/dns_records?per_page=100")
    if not listing.ok:
        report.add("dns", "failed", listing.errors)
        return
    existing = {(r["type"], r["name"]) for r in (listing.result or [])}
    for record in desired:
        fqdn = (
            record["name"]
            if record["name"].endswith(SITE_HOST)
            else f"{record['name']}.{SITE_HOST}"
        )
        if (record["type"], fqdn) in existing:
            report.add(f"dns:{record['type']} {record['name']}", "unchanged")
            continue
        response = client.post(f"/zones/{client.zone_id}/dns_records", {**record, "name": fqdn})
        if response.ok:
            report.add(f"dns:{record['type']} {record['name']}", "updated", "created")
        elif _is_forbidden(response):
            report.add(f"dns:{record['type']} {record['name']}", "manual", FALLBACKS["dns"])
        else:
            report.add(f"dns:{record['type']} {record['name']}", "failed", response.errors)


def managed_ruleset_deployed(client: Client) -> dict[str, Any] | None:
    """The managed ruleset deployed in the firewall phase, read **zone-scoped**.

    Deliberately not `GET /accounts/{id}/rulesets`: T1 is a zone token and listing
    account rulesets would mean widening it to account scope, which is the token working
    as designed rather than a problem to solve. The zone's own ruleset list answers the
    only question that matters — is the managed ruleset deployed here.
    """
    response = client.get(f"/zones/{client.zone_id}/rulesets")
    if not response.ok:
        return None
    for ruleset in response.result or []:
        if ruleset.get("phase") == MANAGED_PHASE and ruleset.get("kind") == "managed":
            return dict(ruleset)
    return None


def apply_rulesets(client: Client, report: Report) -> None:
    for phase in WRITTEN_PHASES:
        path = f"/zones/{client.zone_id}/rulesets/phases/{phase}/entrypoint"
        rules = _load(f"rulesets/{phase}.json")["rules"]
        response = client.put(path, {"rules": rules})
        if response.ok:
            report.add(phase, "updated", f"{len(rules)} rule(s)")
        elif _is_forbidden(response):
            report.add(phase, "manual", FALLBACKS[phase])
        else:
            report.add(phase, "failed", response.errors)

    verify_managed_ruleset(client, report)


def verify_managed_ruleset(client: Client, report: Report) -> None:
    """Confirm Cloudflare's managed ruleset is deployed; never write this phase."""
    deployed = managed_ruleset_deployed(client)
    if deployed is None:
        report.add(
            MANAGED_PHASE,
            "failed",
            "no managed ruleset is deployed in this phase. docs/08 §5.6 assumes Free "
            "zones receive it automatically; if that is no longer true the zone is "
            "running without the Free Managed Ruleset and the assumption needs revisiting.",
        )
        return
    report.add(
        MANAGED_PHASE,
        "skipped",
        f"deployed by Cloudflare as {deployed.get('name')!r} ({deployed.get('id')}); "
        "verified by GET, never written",
    )


def apply_tiered_cache(client: Client, report: Report) -> None:
    path = f"/zones/{client.zone_id}/cache/tiered_cache_smart_topology_enable"
    response = client.patch(path, {"value": "on"})
    if response.ok:
        report.add("tiered-cache", "updated", "smart topology on")
    elif _is_forbidden(response):
        report.add("tiered-cache", "manual", FALLBACKS["tiered-cache"])
    else:
        report.add("tiered-cache", "failed", response.errors)


def apply_url_normalization(client: Client, report: Report) -> None:
    """Read first; write only if it is off. The header rules depend on it (docs/08 §5.3)."""
    path = f"/zones/{client.zone_id}/url_normalization"
    current = client.get(path)
    if _is_forbidden(current) or current.status == HTTP_NOT_FOUND:
        report.add("url-normalization", "manual", FALLBACKS["url-normalization"])
        return
    if not current.ok:
        report.add("url-normalization", "failed", current.errors)
        return
    found = current.result or {}
    if found.get("type") == "cloudflare" and found.get("scope") == "incoming":
        report.add("url-normalization", "unchanged")
        return
    response = client.put(path, {"type": "cloudflare", "scope": "incoming"})
    if response.ok:
        report.add("url-normalization", "updated")
    elif _is_forbidden(response):
        report.add("url-normalization", "manual", FALLBACKS["url-normalization"])
    else:
        report.add("url-normalization", "failed", response.errors)


STEPS = (
    apply_zone_settings,
    apply_bot_management,
    apply_dnssec,
    apply_dns,
    apply_rulesets,
    apply_tiered_cache,
    apply_url_normalization,
)


def run(client: Client) -> Report:
    """Verify the zone, then apply every step. Nothing writes before the verification."""
    report = Report(zone_id=client.zone_id)
    report.hostname = client.verify_zone(SITE_HOST)
    for step in STEPS:
        try:
            step(client, report)
        except ZoneScopeError:
            raise
        except CloudflareError as exc:
            report.add(step.__name__.removeprefix("apply_"), "failed", str(exc))
    return report
