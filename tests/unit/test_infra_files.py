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
    "rulesets/http_request_firewall_custom.json": "### 5.7 ",
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


def test_no_apex_txt_row_is_exclusive() -> None:
    """The apex holds Email Routing's SPF next to the site verification. An exclusive row
    patches its single candidate, so an exclusive apex TXT would overwrite SPF."""
    apex = [r for r in load("dns.json")["records"] if r["name"] == "loremfile.dev"]
    assert [r["type"] for r in apex] == ["TXT"], "control: the apex verification row exists"
    assert not any(r.get("exclusive") for r in apex)


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
    keys = ("index.html", "docs/", "legal/", "assets/", "manifest.json", "_probe/", "_formats/")
    # `pdf` is the format page and `pdf/` the locked prefix: ADR-032 keeps them apart.
    for key in (*keys, ".well-known/", "schema/", "formats", "pdf"):
        assert not any(key.startswith(prefix) for prefix in prefixes), key


def test_the_redirect_targets_the_canonical_host() -> None:
    rule = load("rulesets/http_request_dynamic_redirect.json")["rules"][0]
    target = rule["action_parameters"]["from_value"]["target_url"]["expression"]
    assert SITE_HOST in target
    assert rule["action_parameters"]["from_value"]["preserve_query_string"] is True


# --- display assets: out of the noindex rule, and only those four ------------------------

EQ_PATH = re.compile(r'http\.request\.uri\.path eq "([^"]+)"')


def _header_rules() -> dict[str, dict[str, Any]]:
    doc = load("rulesets/http_response_headers_transform.json")
    return {rule["ref"]: rule for rule in doc["rules"]}


def test_the_noindex_exclusion_names_exactly_the_display_assets() -> None:
    """The rule and the code that verifies it in production must name the same four files.

    Pinned against `routes.DISPLAY_ASSETS` so neither can gain or lose a path alone."""
    from loremfile.site import routes  # noqa: PLC0415

    rule = _header_rules()["files_noindex"]
    excluded = set(EQ_PATH.findall(rule["expression"]))
    assert excluded, "empty-set control: the pattern must find the excluded paths"
    assert excluded == {f"/{key}" for key in routes.DISPLAY_ASSETS}


def test_every_other_file_keeps_exactly_the_headers_it_had() -> None:
    """`files_headers` is unchanged; `files_noindex` is that expression minus the four.

    So a fixture or data file matches both, as it matched the single rule before, and the
    display assets keep `nosniff`, CORP and TAO — only `X-Robots-Tag` leaves them."""
    rules = _header_rules()
    files, noindex = rules["files_headers"], rules["files_noindex"]
    assert files["expression"] == (
        '(http.request.uri.path contains "." and not '
        'ends_with(http.request.uri.path, "/index.html"))'
    ), "files_headers' expression must not change: every fixture depends on it"
    assert noindex["expression"].startswith(files["expression"][:-1] + " and not (")
    assert set(files["action_parameters"]["headers"]) == {
        "X-Content-Type-Options",
        "Cross-Origin-Resource-Policy",
        "Timing-Allow-Origin",
    }
    assert noindex["action_parameters"]["headers"] == {
        "X-Robots-Tag": {"operation": "set", "value": "noindex"}
    }


def test_no_two_header_rules_set_the_same_header_on_the_same_path_family() -> None:
    """`08` §5.3's invariant: X-Robots-Tag is set by `files_noindex` on dotted paths and by
    `legal_pages_noindex` on extensionless ones, never both on one path."""
    rules = _header_rules()
    legal = set(EQ_PATH.findall(rules["legal_pages_noindex"]["expression"]))
    assert legal, "empty-set control"
    assert all("." not in path for path in legal)
    assert 'contains "."' in rules["files_noindex"]["expression"]
