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
