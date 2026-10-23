"""The agent discovery files: Content Signals, the Link header, the API catalog and the skills.

Checked against the specs as read on 2026-09-21 — contentsignals.org, RFC 8288 with the IANA
link relation registry, RFC 9727, and Agent Skills Discovery v0.2.0 — and against one rule
of this site's own: none of them may list or link a legal page (ADR-028).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from loremfile.infra import purge, verify_live
from loremfile.site import build, checks, routes

ROOT = Path(__file__).resolve().parents[2]
WHEN = dt.datetime(2026, 9, 15, 12, 0, tzinfo=dt.UTC)
SIGNAL = "Content-Signal: search=yes, ai-input=yes, ai-train=yes"


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("built") / "site"
    build.build(out, root=ROOT, committed=WHEN)
    return out


def read(site: Path, key: str) -> str:
    return (site / routes.disk_path(key)).read_text(encoding="utf-8")


# --- robots.txt ------------------------------------------------------------------------


def test_every_robots_group_carries_the_content_signal() -> None:
    """A crawler obeys only its most specific group (RFC 9309 §2.2.1), so a signal in the
    `*` group alone would never reach the AI crawlers the named group matches."""
    groups = build.ROBOTS_TXT.split("\n\n")[:2]
    assert [g.splitlines()[0] for g in groups] == ["User-agent: *", "User-agent: GPTBot"]
    for group in groups:
        lines = group.splitlines()
        assert lines.count(SIGNAL) == 1
        rules = [i for i, line in enumerate(lines) if line.startswith(("Allow:", "Disallow:"))]
        assert lines.index(SIGNAL) < min(rules), "the signal belongs before the group's rules"


# --- the Link header -------------------------------------------------------------------


def header_rule() -> dict[str, object]:
    path = ROOT / "infra" / "rulesets" / "http_response_headers_transform.json"
    rules = json.loads(path.read_text(encoding="utf-8"))["rules"]
    return next(r for r in rules if r["ref"] == "site_pages_headers")


def test_verify_live_expects_exactly_what_the_page_rule_sets() -> None:
    headers = header_rule()["action_parameters"]["headers"]  # type: ignore[index]
    rule = {name.lower(): spec["value"] for name, spec in headers.items()}
    assert rule == verify_live.EXPECTED_PAGE_HEADERS
    assert rule["link"] == routes.LINK_HEADER


def test_the_link_header_uses_registered_relations_to_files_the_site_publishes(
    site: Path,
) -> None:
    links = re.findall(r'<([^>]+)>; rel="([^"]+)"', routes.LINK_HEADER)
    assert links == [("/llms.txt", "describedby"), ("/.well-known/api-catalog", "api-catalog")]
    built = routes.site_files(site)
    assert all(routes.key_for(target) in built for target, _ in links)


def test_the_api_catalog_answers_head_with_the_link_too() -> None:
    """RFC 9727 §2: a HEAD of the catalog carries the api-catalog relation."""
    assert 'eq "/.well-known/api-catalog"' in str(header_rule()["expression"])


# --- the API catalog -------------------------------------------------------------------


def test_the_catalog_is_a_linkset_served_with_its_profile(site: Path) -> None:
    key = routes.API_CATALOG_KEY
    assert not routes.is_page(key) and routes.disk_path(key) == key
    assert routes.content_type(key).startswith("application/linkset+json; profile=")
    linkset = json.loads(read(site, key))["linkset"]
    anchors = [entry["anchor"] for entry in linkset]
    formats = {e["format"] for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
    assert anchors[:2] == [
        "https://loremfile.dev/manifest.json",
        "https://loremfile.dev/sha256sums.txt",
    ]
    assert set(anchors[2:]) == {f"https://loremfile.dev/{fmt}/index.json" for fmt in formats}
    manifest = linkset[0]
    assert manifest["service-desc"][0]["href"] == "https://loremfile.dev/schema/manifest-v1.json"
    assert all(e["service-doc"][0]["href"] == "https://loremfile.dev/llms.txt" for e in linkset)


# --- the skills ------------------------------------------------------------------------


def test_the_skills_index_lists_the_skill_with_the_digest_of_its_bytes(site: Path) -> None:
    index = json.loads(read(site, routes.AGENT_SKILLS_INDEX_KEY))
    assert index["$schema"] == "https://schemas.agentskills.io/discovery/0.2.0/schema.json"
    [skill] = index["skills"]
    assert skill["url"] == "/.well-known/agent-skills/find-and-verify-fixtures/SKILL.md"
    data = (site / skill["url"].lstrip("/")).read_bytes()
    assert skill["digest"] == f"sha256:{hashlib.sha256(data).hexdigest()}"
    assert data.decode().startswith(
        f"---\nname: {skill['name']}\ndescription: {skill['description']}\n---\n"
    )
    assert routes.content_type(skill["url"].lstrip("/")) == "text/markdown; charset=utf-8"


def test_a_skill_whose_frontmatter_names_another_skill_is_refused(tmp_path: Path) -> None:
    skill = tmp_path / "site" / "agent-skills" / build.AGENT_SKILL
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: other\ndescription: x\n---\n# x\n")
    with pytest.raises(build.SiteError, match="frontmatter"):
        build.agent_skills(tmp_path)


# --- the build-time checks, and that they fire -----------------------------------------


def test_the_built_files_pass_and_name_no_legal_page(site: Path) -> None:
    keys = set(routes.site_files(site))
    assert checks._agent_problems(site, keys, lambda k: read(site, k) if k in keys else "") == []


@pytest.fixture
def broken(site: Path, tmp_path: Path) -> Path:
    copy = tmp_path / "site"
    shutil.copytree(site, copy)
    return copy


def problems(site: Path) -> list[str]:
    keys = set(routes.site_files(site))
    return checks._agent_problems(site, keys, lambda k: read(site, k) if k in keys else "")


def test_a_catalog_that_links_a_legal_page_or_nothing_real_fails(broken: Path) -> None:
    path = broken / routes.API_CATALOG_KEY
    document = json.loads(path.read_text())
    document["linkset"].append({"anchor": "https://loremfile.dev/legal/imprint", "item": []})
    path.write_text(json.dumps(document))
    found = problems(broken)
    assert any("names a legal page" in p for p in found)
    assert any("carries no link relation" in p for p in found)
    path.write_text("{}")
    assert any("no `linkset` array" in p for p in problems(broken))


def test_a_skill_edited_without_its_digest_fails(broken: Path) -> None:
    skill = broken / ".well-known/agent-skills/find-and-verify-fixtures/SKILL.md"
    skill.write_text(skill.read_text() + "\nOne more line.\n")
    assert any("digest is not the SHA-256" in p for p in problems(broken))


def test_missing_discovery_files_fail_rather_than_pass(broken: Path) -> None:
    (broken / routes.API_CATALOG_KEY).unlink()
    (broken / routes.AGENT_SKILLS_INDEX_KEY).unlink()
    (broken / "robots.txt").write_text(build.ROBOTS_TXT.replace(f"{SIGNAL}\n", ""))
    found = problems(broken)
    assert any(routes.API_CATALOG_KEY in p for p in found)
    assert any(routes.AGENT_SKILLS_INDEX_KEY in p for p in found)
    assert any("no Content-Signal" in p for p in found)


def test_the_new_files_are_purged_on_deploy() -> None:
    prefixes, files = purge.site_targets([])
    assert "loremfile.dev/.well-known/agent-skills/" in prefixes
    assert "https://loremfile.dev/.well-known/api-catalog" in files


# --- every agent-facing surface is in the skill, or left out on purpose (2026-10-12) ------
#
# The third time a surface reached agents without reaching the one document written for
# them: the MCP server, then the Markdown twins and the JSON-LD hashes, all missing from
# SKILL.md. Surfaces are discovered from the build, not listed here from memory, so a new one
# fails until someone decides whether agents should be told about it.

#: Surface -> the text that shows SKILL.md tells agents about it.
IN_THE_SKILL = {
    "manifest.json": "https://loremfile.dev/manifest.json",
    # A pattern, not an absolute URL with braces, which a crawler would fetch as a 404.
    "{format}/index.json": "GET /{format}/index.json",
    "sha256sums.txt": "https://loremfile.dev/sha256sums.txt",
    "llms.txt": "https://loremfile.dev/llms.txt",
    "llms-full.txt": "https://loremfile.dev/llms-full.txt",
    "Markdown twins": "append `/index.md`",
    "MCP server": "uvx loremfile mcp",
    ".well-known/api-catalog": "https://loremfile.dev/.well-known/api-catalog",
    "JSON-LD hashes": "`contentSize` and `sha256`",
}
#: Surface -> why the skill does not mention it.
LEFT_OUT = {
    "formats.json": "manifest.json's `formats` names the same formats; one entry point is enough",
    "search-index.json": "the home page's search box reads it; its shape is not a contract",
    "sitemap.xml": "lists pages for crawlers, not files",
    "robots.txt": "crawler policy, not a way to find or verify a file",
    ".well-known/security.txt": "for reporting a vulnerability, not for using the files",
    ".well-known/agent-skills/index.json": "the index that lists this skill",
    ".well-known/agent-skills/find-and-verify-fixtures/SKILL.md": "the skill itself",
    "schema/manifest-v1.json": "the manifest's schema, linked from the api-catalog the skill names",
    routes.INDEXNOW_KEY_FILE: "proves ownership of the site to IndexNow; nothing to use",
}


def surfaces(keys: set[str], llms_text: str) -> set[str]:
    """Agent-facing surfaces: built files that are neither pages nor display assets, the
    per-format lists and twins as one surface each, and the two that are not files at all,
    found by what llms.txt's How to use says about them."""
    found: set[str] = set()
    for key in keys:
        if routes.is_page(key) or key in routes.DISPLAY_ASSETS or key.startswith("assets/"):
            continue
        if key.startswith(f"{routes.FORMAT_INDEX_DIR}/"):
            found.add("Markdown twins" if key.endswith(".md") else "{format}/index.json")
        else:
            found.add(key)
    how_to_use = llms_text.split("## How to use\n", 1)[1].split("\n## ", 1)[0]
    if "loremfile mcp" in how_to_use:
        found.add("MCP server")
    if "contentSize and sha256" in how_to_use:
        found.add("JSON-LD hashes")
    return found


def unaccounted(found: set[str], skill: str) -> list[str]:
    """Surfaces neither in the skill nor left out on purpose, and listed ones that are gone
    or that the skill no longer mentions."""
    problems = [
        f"{s}: neither in SKILL.md nor in LEFT_OUT"
        for s in sorted(found)
        if s not in IN_THE_SKILL and s not in LEFT_OUT
    ]
    problems += [
        f"{s}: listed, but no longer published" for s in sorted({*IN_THE_SKILL, *LEFT_OUT} - found)
    ]
    problems += [
        f"{s}: SKILL.md does not say {t!r}"
        for s, t in sorted(IN_THE_SKILL.items())
        if t not in skill
    ]
    return problems


def test_every_agent_facing_surface_is_in_the_skill_or_left_out_with_a_reason(site: Path) -> None:
    keys = set(routes.site_files(site))
    found = surfaces(keys, read(site, "llms.txt"))
    assert {"manifest.json", "Markdown twins", "MCP server", "JSON-LD hashes"} <= found
    skill = read(site, ".well-known/agent-skills/find-and-verify-fixtures/SKILL.md")
    assert unaccounted(found, skill) == []
    assert all(reason.strip() for reason in LEFT_OUT.values())


def test_a_new_surface_or_a_forgotten_one_is_named() -> None:
    llms_text = "## How to use\n- MCP server: `uvx loremfile mcp`\n\n## Formats\n"
    found = surfaces({"manifest.json", "pdf", "assets/x.css", "feeds/new.json"}, llms_text)
    assert found == {"manifest.json", "feeds/new.json", "MCP server"}
    problems = unaccounted(found, "Only https://loremfile.dev/manifest.json here.")
    assert "feeds/new.json: neither in SKILL.md nor in LEFT_OUT" in problems
    assert "MCP server: SKILL.md does not say 'uvx loremfile mcp'" in problems
    assert "llms.txt: listed, but no longer published" in problems
