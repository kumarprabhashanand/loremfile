"""The two legal pages that name the operator: out of search, AI crawlers and every index.

`/legal/imprint` and `/legal/privacy` carry the operator's name and address (ADR-028). The
values never enter the repository, so nothing here can test them; these tests guard the
parts that do live here — the edge header rule, the robots.txt specification, and the
placeholder hygiene of the templates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LEGAL_PAGES = {"/legal/imprint", "/legal/privacy"}
DIRECTIVE = "noindex, nofollow, nosnippet"
#: Each checked against its vendor's own documentation (docs/04 §6). Adding one means
#: checking that vendor's documentation first.
AI_TOKENS = {
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "OAI-AdsBot",
    "ClaudeBot",
    "Claude-User",
    "Claude-SearchBot",
    "Google-Extended",
}
PLACEHOLDER = re.compile(r"%%IMPRINT_[A-Z_]+%%")


def ruleset(name: str) -> list[dict[str, Any]]:
    path = ROOT / "infra" / "rulesets" / f"{name}.json"
    return list(json.loads(path.read_text(encoding="utf-8"))["rules"])


def rule(ref: str) -> dict[str, Any]:
    return next(r for r in ruleset("http_response_headers_transform") if r["ref"] == ref)


def ai_agent_rule() -> dict[str, Any]:
    return next(
        r
        for r in ruleset("http_request_firewall_custom")
        if r["ref"] == "loremfile_legal_pages_ai_agents"
    )


# --- the edge header rule -----------------------------------------------------


def test_the_legal_rule_targets_exactly_the_two_pages() -> None:
    expression = rule("legal_pages_noindex")["expression"]
    assert set(re.findall(r'http\.request\.uri\.path eq "([^"]+)"', expression)) == LEGAL_PAGES
    # Negative control: the other legal pages stay indexable (ADR-016).
    assert "/legal/license" not in expression
    assert "/legal/terms" not in expression


def test_the_legal_rule_sets_only_the_robots_directive() -> None:
    headers = rule("legal_pages_noindex")["action_parameters"]["headers"]
    assert headers == {"X-Robots-Tag": {"operation": "set", "value": DIRECTIVE}}


def test_the_site_page_rule_sets_no_robots_tag_so_the_two_never_collide() -> None:
    assert "X-Robots-Tag" not in rule("site_pages_headers")["action_parameters"]["headers"]


def test_transform_rules_stay_within_the_free_plan() -> None:
    total = len(ruleset("http_request_transform")) + len(ruleset("http_response_headers_transform"))
    assert total == 6
    assert total <= 10


# --- robots.txt, as specified ---------------------------------------------------


def robots_spec() -> str:
    text = (ROOT / "docs" / "04-manifest-and-discovery.md").read_text(encoding="utf-8")
    section = text.split("## 6. `robots.txt`", 1)[1]
    match = re.search(r"```\n(.*?)```", section, re.S)
    assert match, "docs/04 §6 has no robots.txt block"
    return match.group(1)


def groups(robots: str) -> list[tuple[set[str], list[tuple[str, str]]]]:
    """RFC 9309 groups: consecutive user-agent lines, then the rules that follow them."""
    parsed: list[tuple[set[str], list[tuple[str, str]]]] = []
    agents: set[str] = set()
    rules: list[tuple[str, str]] = []
    for raw in robots.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("sitemap:"):
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if rules:
                parsed.append((agents, rules))
                agents, rules = set(), []
            agents.add(value)
        else:
            rules.append((key, value))
    if agents:
        parsed.append((agents, rules))
    return parsed


def test_the_groups_the_assertions_are_about_exist() -> None:
    """Empty-set control first (AGENTS.md): every assertion below is vacuous if parsing
    found nothing, so name the groups that must be there."""
    found = groups(robots_spec())
    assert any("*" in agents for agents, _ in found)
    assert any("GPTBot" in agents for agents, _ in found)


def test_everyone_may_still_crawl_so_noindex_can_be_seen() -> None:
    """Google honours noindex only on a page it is not blocked from crawling."""
    star = next(rules for agents, rules in groups(robots_spec()) if "*" in agents)
    assert ("allow", "/") in star
    assert not [value for key, value in star if key == "disallow"]


def test_the_ai_group_names_exactly_the_verified_tokens_and_blocks_only_the_legal_pages() -> None:
    ai = [(agents, rules) for agents, rules in groups(robots_spec()) if agents & AI_TOKENS]
    assert len(ai) == 1, "one group, so no token is left in a different rule set"
    agents, rules = ai[0]
    assert agents == AI_TOKENS
    assert {value for key, value in rules if key == "disallow"} == LEGAL_PAGES
    assert not [value for key, value in rules if key == "allow"]


# --- the WAF rule that refuses what robots.txt only asks (ADR-030) -------------------


def test_the_waf_rule_refuses_the_robots_tokens_except_google_extended() -> None:
    """One list, two enforcements. `Google-Extended` sends no requests of its own, so a
    clause for it could never fire; every other token is refused on the two pages."""
    expression = ai_agent_rule()["expression"]
    tokens = re.findall(r'http\.user_agent contains "([^"]+)"', expression)
    assert tokens, "empty-set control: the pattern must find the rule's tokens"
    assert set(tokens) == AI_TOKENS - {"Google-Extended"}
    assert "Google-Extended" not in expression
    assert set(re.findall(r'http\.request\.uri\.path eq "([^"]+)"', expression)) == LEGAL_PAGES
    assert "lower(" not in expression, "tokens are matched in the vendor's casing (ADR-030)"
    assert ai_agent_rule()["action"] == "block"


# --- placeholders -----------------------------------------------------------------


def test_the_templates_carry_the_imprint_placeholders() -> None:
    text = (ROOT / "docs" / "13-legal-and-policy.md").read_text(encoding="utf-8")
    found = set(PLACEHOLDER.findall(text))
    assert {"%%IMPRINT_NAME%%", "%%IMPRINT_STREET%%", "%%IMPRINT_POSTAL_CITY%%"} <= found


def test_the_retired_placeholders_are_gone_from_the_living_documents() -> None:
    """The changelog keeps its history; these are the documents an agent reads for rules."""
    retired = ("<" + "CONTROLLER>", "<" + "CONTACT_EMAIL>")
    for relative in (
        "AGENTS.md",
        "docs/README.md",
        "docs/07-website.md",
        "docs/13-legal-and-policy.md",
        "docs/18-open-questions.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for token in retired:
            assert token not in text, f"{relative} still has {token}"
