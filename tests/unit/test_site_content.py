"""M4.2: the written pages say only what the catalog says (docs/07 §5)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "site" / "content"
PATH_SHAPE = re.compile(r"[a-z0-9]+/[a-z0-9._/-]+\.[a-z0-9]+")
CODE = re.compile(r"`([^`\s]+)`")
URL = re.compile(r"https://loremfile\.dev/([^\s)`\"'<>]+)")
WORD = re.compile(r"[A-Za-z0-9][\w'.,/-]*")
FORMAT_PAGES = sorted((CONTENT / "formats").glob("*.md"))


def words(text: str) -> int:
    return len(WORD.findall(re.sub(r"\]\([^)]*\)", "]", text)))


def active_paths() -> set[str]:
    document = json.loads((ROOT / "manifest.json").read_text())
    return {e["path"] for e in document["fixtures"] if e.get("status", "active") == "active"}


def named_paths(text: str) -> set[str]:
    candidates = CODE.findall(text) + [url.rstrip(".,") for url in URL.findall(text)]
    return {token for token in candidates if PATH_SHAPE.fullmatch(token)}


def test_every_published_format_has_its_page_text() -> None:
    formats = {path.split("/", 1)[0] for path in active_paths()}
    assert formats <= {page.stem for page in FORMAT_PAGES}


@pytest.mark.parametrize("page", FORMAT_PAGES, ids=lambda page: page.stem)
def test_a_format_page_is_120_to_250_words_and_names_its_own_files(page: Path) -> None:
    text = page.read_text(encoding="utf-8")
    assert 120 <= words(text) <= 250
    assert any(path.startswith(f"{page.stem}/") for path in named_paths(text))
    assert not text.startswith("#"), "the template supplies the H1"


@pytest.mark.parametrize("name", ["getting-started", "naming", "faq"])
def test_a_documentation_page_is_at_least_120_words(name: str) -> None:
    assert words((CONTENT / "pages" / f"{name}.md").read_text(encoding="utf-8")) >= 120


def test_every_fixture_path_the_content_names_exists() -> None:
    named: set[str] = set()
    for page in CONTENT.rglob("*.md"):
        named |= named_paths(page.read_text(encoding="utf-8"))
    assert len(named) > 100, "empty-set control: the pattern must find the named paths"
    assert sorted(named - active_paths()) == []
