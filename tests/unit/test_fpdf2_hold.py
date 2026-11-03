"""The fpdf2 hold: tools/requirements.in, .github/dependabot.yml, docs/06 §4 (#134).

fpdf2 2.9.0 writes a Letter page's MediaBox as `612 792` where 2.8.9 wrote `612.00 792.00`,
so it changes the bytes of the published `pdf/letter-1page.pdf` and, in the fleet audit,
nothing else. Published bytes are frozen, so the library waits below 2.9 until that file is
superseded by a new path. This is the pyarrow hold's shape (docs/06 §4).

What is pinned is mechanical: the specifier, the locked version, the manifest's
`supersededBy`, and the Dependabot ignore. Whether the reason is well put is for review.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]
HELD_FROM = Version("2.9.0")
FROZEN = "pdf/letter-1page.pdf"
SEMVER_LEVELS = {"version-update:semver-minor", "version-update:semver-major"}


def requirement_line(text: str, name: str) -> str:
    """The one direct-dependency line of a requirements.in that names `name`."""
    lines = [
        line.split("#")[0].strip()
        for line in text.splitlines()
        if line.split("#")[0].strip().lower().startswith(name)
    ]
    assert len(lines) == 1, f"expected one {name} line, found {lines}"
    return lines[0]


def locked_version(lock: str, name: str) -> Version:
    found = re.findall(rf"^{re.escape(name)}==([^\s\\]+)", lock, flags=re.MULTILINE)
    assert len(found) == 1, f"expected one {name} pin in the lock, found {found}"
    return Version(found[0])


def hold_problems(specifier: SpecifierSet, locked: Version, superseded: bool) -> list[str]:
    """Why fpdf2 2.9 or later may not be allowed yet. Empty once the frozen file is superseded."""
    if superseded:
        return []
    problems = []
    if specifier.contains(HELD_FROM, prereleases=True):
        problems.append(f"requirements.in admits fpdf2 {HELD_FROM} and {FROZEN} is not superseded")
    if locked >= HELD_FROM:
        problems.append(f"the lock pins fpdf2 {locked} and {FROZEN} is not superseded")
    return problems


def dependabot_gap(config: dict[str, Any]) -> list[str]:
    """What the pip entry's `ignore` is missing for fpdf2 (minor and major updates)."""
    pip = [u for u in config["updates"] if u["package-ecosystem"] == "pip"]
    assert len(pip) == 1, "one pip entry"
    for rule in pip[0].get("ignore", []):
        if rule["dependency-name"] == "fpdf2":
            missing = SEMVER_LEVELS - set(rule.get("update-types", []))
            return sorted(missing)
    return sorted(SEMVER_LEVELS)


REQUIREMENTS = (ROOT / "tools" / "requirements.in").read_text(encoding="utf-8")
LOCK = (ROOT / "tools" / "requirements.lock").read_text(encoding="utf-8")
MANIFEST = {e["path"]: e for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
SPECIFIER = Requirement(requirement_line(REQUIREMENTS, "fpdf2")).specifier


def is_superseded(manifest: dict[str, Any] = MANIFEST) -> bool:
    return bool(manifest[FROZEN].get("supersededBy"))


def docs_state_the_hold(docs: str, line: str | None = None) -> bool:
    """The whole specifier, not a prefix of it: `fpdf2>=2.8.9` alone must not satisfy this."""
    wanted = re.escape(line or requirement_line(REQUIREMENTS, "fpdf2"))
    return re.search(wanted + r"(?![\w.,<>=!~])", docs) is not None


# --- the committed state ----------------------------------------------------------------


def test_the_discovery_finds_what_the_hold_is_about() -> None:
    """Empty-set control first: every assertion below is vacuous if nothing was found."""
    assert requirement_line(REQUIREMENTS, "fpdf2").startswith("fpdf2>=2.8.9")
    assert SPECIFIER.contains(Version("2.8.9")), "the current pin still satisfies it"
    assert locked_version(LOCK, "fpdf2") >= Version("2.8.9")
    assert FROZEN in MANIFEST
    assert MANIFEST["jpg/cmyk-640x480.jpg"]["supersededBy"], "the precedent the exit names exists"


def test_fpdf2_is_held_below_2_9_until_the_frozen_file_is_superseded() -> None:
    assert hold_problems(SPECIFIER, locked_version(LOCK, "fpdf2"), is_superseded()) == []


def test_dependabot_does_not_propose_the_held_versions() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    assert dependabot_gap(config) == []


def test_docs_06_carries_the_specifier_exactly_as_requirements_in_writes_it() -> None:
    """A substring of a known key: the hold in the docs is the hold in the file."""
    docs = (ROOT / "docs" / "06-generation-pipeline.md").read_text(encoding="utf-8")
    assert docs_state_the_hold(docs)


# --- the controls: each check must be able to fire --------------------------------------


def test_control_a_floor_without_a_ceiling_is_refused() -> None:
    problems = hold_problems(SpecifierSet(">=2.8.9"), Version("2.8.9"), superseded=False)
    assert problems == [f"requirements.in admits fpdf2 2.9.0 and {FROZEN} is not superseded"]


def test_control_a_lock_at_2_9_is_refused_even_with_the_ceiling_in_place() -> None:
    problems = hold_problems(SpecifierSet(">=2.8.9,<2.9"), Version("2.9.0"), superseded=False)
    assert problems == [f"the lock pins fpdf2 2.9.0 and {FROZEN} is not superseded"]


def test_control_the_exit_clears_both_once_the_file_is_superseded() -> None:
    assert hold_problems(SpecifierSet(">=2.8.9"), Version("2.9.0"), superseded=True) == []


def test_control_the_hold_as_written_passes_while_the_file_is_published() -> None:
    assert hold_problems(SpecifierSet(">=2.8.9,<2.9"), Version("2.8.9"), superseded=False) == []


def test_control_the_manifest_reader_sees_a_supersession_and_its_absence() -> None:
    """The exit keys on `supersededBy`, read the way the manifest writes it."""
    assert is_superseded({FROZEN: {"supersededBy": "pdf/letter-1page-v2.pdf"}}) is True
    assert is_superseded({FROZEN: {"supersededBy": None}}) is False
    assert is_superseded({FROZEN: {}}) is False


def test_control_a_dependabot_config_without_the_ignore_is_refused() -> None:
    bare = {"updates": [{"package-ecosystem": "pip", "ignore": [{"dependency-name": "pyarrow"}]}]}
    assert dependabot_gap(bare) == sorted(SEMVER_LEVELS)
    patch_only = {
        "updates": [
            {
                "package-ecosystem": "pip",
                "ignore": [
                    {
                        "dependency-name": "fpdf2",
                        "update-types": ["version-update:semver-minor"],
                    }
                ],
            }
        ]
    }
    assert dependabot_gap(patch_only) == ["version-update:semver-major"]


def test_control_the_docs_check_fires_on_a_doc_that_lacks_the_specifier() -> None:
    held = "fpdf2>=2.8.9,<2.9"
    assert docs_state_the_hold("fpdf2>=2.8 is what this doc says", held) is False
    assert docs_state_the_hold("held at fpdf2>=2.8.9,<2.9 for now", held) is True
    assert docs_state_the_hold("held at fpdf2>=2.8.9,<2.9.1 for now", held) is False, "longer"
    assert docs_state_the_hold("only the floor, fpdf2>=2.8.9, is named", held) is False, "prefix"
