"""M2.1: `infra/` must be exactly what docs/08 specifies, and stay that way.

The files were generated from docs/08's own JSON blocks, so they cannot have been
mistranscribed. This test keeps them that way: it re-parses the document and compares.
That is the rule M3.6 settled — make a claim checkable when a future decision rests on
it. The desired state *is* the claim, and `apply.py` PUTs it into a live zone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from loremfile.catalog import Catalog
from loremfile.config import SITE_HOST
from loremfile.infra import apply as apply_module
from loremfile.infra import locks

DOC = Path(__file__).resolve().parents[2] / "docs" / "08-infrastructure.md"
INFRA = apply_module.infra_dir()


def blocks_after(marker: str) -> list[dict[str, Any]]:
    text = DOC.read_text(encoding="utf-8")
    start = text.index(marker)
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)```", text[start:], re.S)]


def load(name: str) -> Any:
    return json.loads((INFRA / name).read_text(encoding="utf-8"))


SPEC = {
    "zone-settings.json": "## 3. Zone settings",
    "bot-management.json": "## 4. Bot management",
    "rulesets/http_request_dynamic_redirect.json": "### 5.1 ",
    "rulesets/http_request_transform.json": "### 5.2 ",
    "rulesets/http_response_headers_transform.json": "### 5.3 ",
    "rulesets/http_request_cache_settings.json": "### 5.4 ",
    "rulesets/http_ratelimit.json": "### 5.5 ",
    "rulesets/http_request_firewall_managed.json": "### 5.6 ",
    "dns.json": "`infra/dns.json` (desired records",
}


@pytest.mark.parametrize(("name", "marker"), sorted(SPEC.items()))
def test_each_file_matches_the_specification(name: str, marker: str) -> None:
    assert load(name) == blocks_after(marker)[0], (
        f"infra/{name} has drifted from docs/08 {marker.strip()}. Change the document "
        "and the file in the same pull request, or apply.py will write something the "
        "specification does not describe."
    )


def test_every_owned_phase_has_a_file_and_no_others_exist() -> None:
    """A phase file we do not own would be PUT into a zone we share with other sites."""
    on_disk = {p.stem for p in (INFRA / "rulesets").glob("*.json")}
    assert on_disk == set(apply_module.PHASES)


def test_every_rule_has_a_stable_ref() -> None:
    """docs/08 §5: refs are how an audit diffs rules; a missing one makes drift invisible."""
    for name in SPEC:
        if not name.startswith("rulesets/"):
            continue
        refs = [rule.get("ref") for rule in load(name)["rules"]]
        assert all(refs), f"{name}: a rule has no ref"
        assert len(set(refs)) == len(refs), f"{name}: duplicate refs"


def test_the_settings_that_would_rewrite_response_bodies_are_off() -> None:
    """These change fixture bytes in flight, which breaks the product's core promise."""
    settings = load("zone-settings.json")
    for key in (
        "rocket_loader",
        "email_obfuscation",
        "automatic_https_rewrites",
        "server_side_exclude",
        "polish",
        "mirage",
    ):
        assert settings[key] == "off", f"{key} rewrites response bodies"
    assert settings["hotlink_protection"] == "off", "hotlinking is the product"


def test_the_rate_limit_matches_the_free_plan_constraints() -> None:
    """docs/08 §5.5: one rule, 10 s period, and cf.colo.id is mandatory in every rule."""
    rules = load("rulesets/http_ratelimit.json")["rules"]
    assert len(rules) == 1
    limit = rules[0]["ratelimit"]
    assert limit["period"] == 10
    assert limit["mitigation_timeout"] == 10
    assert set(limit["characteristics"]) == {"cf.colo.id", "ip.src"}
    assert "cf.colo.id" not in rules[0]["expression"], "colo is a characteristic, not a field"


def test_the_cache_rule_ignores_the_query_string() -> None:
    """Without this every `?x=1` is a separate cache entry and a separate R2 read."""
    rule = load("rulesets/http_request_cache_settings.json")["rules"][0]
    key = rule["action_parameters"]["cache_key"]["custom_key"]["query_string"]
    assert key == {"exclude": "*"}, "docs/08 §5.4: M2.3 confirms the literal the API takes"


def test_the_sandbox_csp_never_allows_script() -> None:
    """A markup fixture is untrusted content served from our own origin."""
    for rule in load("rulesets/http_response_headers_transform.json")["rules"]:
        headers = rule["action_parameters"]["headers"]
        csp = headers.get("Content-Security-Policy", {}).get("value", "")
        if "sandbox" in csp:
            assert "script-src" not in csp
            assert "default-src 'none'" in csp


def test_dns_desired_records_are_only_the_ones_we_own() -> None:
    """Email Routing owns MX and SPF; apply.py must never be told to create them."""
    document = load("dns.json")
    kinds = {record["type"] for record in document["records"]}
    assert "MX" not in kinds
    # `v=spf1`, not the substring "spf": DMARC's own `aspf=s` alignment tag contains it.
    assert not any(record["content"].lower().startswith("v=spf1") for record in document["records"])
    assert "TXT SPF (Email Routing)" in document["expected_managed"]


def test_the_two_cors_files_describe_the_same_policy() -> None:
    s3 = load("r2-cors.json")[0]
    wrangler = load("r2-cors.wrangler.json")["rules"][0]
    assert wrangler["allowed"]["origins"] == s3["AllowedOrigins"]
    assert wrangler["allowed"]["methods"] == s3["AllowedMethods"]
    assert wrangler["allowed"]["headers"] == s3["AllowedHeaders"]
    assert wrangler["exposeHeaders"] == s3["ExposeHeaders"]
    assert wrangler["maxAgeSeconds"] == s3["MaxAgeSeconds"]


def test_cors_allows_reading_but_not_writing() -> None:
    methods = set(load("r2-cors.json")[0]["AllowedMethods"])
    assert methods == {"GET", "HEAD"}


def test_every_format_prefix_has_a_lock_rule() -> None:
    """A format added without its rule is a prefix a leaked T2 could overwrite."""
    assert locks.diff(Catalog.load()) == []
    prefixes = {rule["prefix"] for rule in load("r2-locks.json")["rules"]}
    assert locks.LOCKTEST_PREFIX in prefixes, "M2.4 needs a prefix holding no fixture"
    for fixture_format in {f.format for f in Catalog.load().fixtures()}:
        assert f"{fixture_format}/" in prefixes


def test_site_keys_are_outside_every_locked_prefix() -> None:
    """The site is rewritten on every deploy; locking it would break deployment."""
    prefixes = {rule["prefix"] for rule in load("r2-locks.json")["rules"]}
    for key in ("index.html", "docs/", "legal/", "assets/", "manifest.json", "_probe/"):
        assert not any(key.startswith(prefix) for prefix in prefixes), key


def test_the_redirect_targets_the_canonical_host() -> None:
    rule = load("rulesets/http_request_dynamic_redirect.json")["rules"][0]
    target = rule["action_parameters"]["from_value"]["target_url"]["expression"]
    assert SITE_HOST in target
    assert rule["action_parameters"]["from_value"]["preserve_query_string"] is True
