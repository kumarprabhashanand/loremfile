"""M4.2: the written pages say only what the catalog says (docs/07 §5)."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest

from loremfile.site import build

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


#: A count of files written into prose. The page's own table prints the files, so a count
#: in a sentence is a second copy that nobody updates: `csv.md` said "Three variants" for
#: two days after a fourth was published. Only this one phrase is checked. A general
#: search for numbers in prose was tried and finds "1,152 samples" and "several messages
#: in one file", neither of which is a claim about the catalog.
VARIANT_CLAIM = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+) variants?\b", re.IGNORECASE
)
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def variant_claims(text: str) -> list[tuple[str, int, set[str]]]:
    """Every "<number> variants" phrase, with the files named after it in its paragraph.

    The files after the phrase are the list it introduces, and they are catalog paths:
    `test_every_fixture_path_the_content_names_exists` already requires each one to be an
    active fixture, so counting them is counting the catalog.
    """
    claims: list[tuple[str, int, set[str]]] = []
    for paragraph in re.split(r"\n\s*\n", text):
        for match in VARIANT_CLAIM.finditer(paragraph):
            stated = match.group(1).lower()
            number = NUMBER_WORDS.get(stated) or int(stated)
            claims.append((match.group(0), number, named_paths(paragraph[match.end() :])))
    return claims


def test_every_published_format_has_its_page_text() -> None:
    formats = {path.split("/", 1)[0] for path in active_paths()}
    assert formats <= {page.stem for page in FORMAT_PAGES}


@pytest.mark.parametrize("page", FORMAT_PAGES, ids=lambda page: page.stem)
def test_a_format_page_is_120_to_250_words_and_names_its_own_files(page: Path) -> None:
    text = page.read_text(encoding="utf-8")
    assert 120 <= words(text) <= 250
    assert any(path.startswith(f"{page.stem}/") for path in named_paths(text))
    assert not text.startswith("#"), "the template supplies the H1"


#: The pages that rank in search (Search Console, October 2026). Each opens with one
#: sentence answering the query, then its file and measured facts, then the explanation.
LEADING_PAGES = {"arrow", "docx", "hls", "m4a", "md", "ogg", "opus", "rtf", "tiff", "wav"}
FILE_MARKER = re.compile(r"^<!-- file: (\S+) -->$", re.M)


def test_the_ranking_pages_open_with_one_sentence_and_then_their_file() -> None:
    leading = {
        page.stem for page in FORMAT_PAGES if FILE_MARKER.search(page.read_text(encoding="utf-8"))
    }
    assert leading == LEADING_PAGES
    for name in sorted(LEADING_PAGES):
        text = (CONTENT / "formats" / f"{name}.md").read_text(encoding="utf-8")
        opening, marker = re.split(r"\n\s*\n", text)[:2]
        assert FILE_MARKER.fullmatch(marker.strip()), f"{name}.md: the file follows one paragraph"
        assert len(re.findall(r"[.!?](?:\s|$)", opening)) == 1, f"{name}.md: one opening sentence"


@pytest.mark.parametrize("name", ["getting-started", "naming", "faq", "languages", "mcp"])
def test_a_documentation_page_is_at_least_120_words(name: str) -> None:
    assert words((CONTENT / "pages" / f"{name}.md").read_text(encoding="utf-8")) >= 120


@pytest.mark.parametrize("page", FORMAT_PAGES, ids=lambda page: page.stem)
def test_a_page_that_counts_variants_counts_the_right_number(page: Path) -> None:
    for phrase, stated, named in variant_claims(page.read_text(encoding="utf-8")):
        assert stated == len(named), (
            f"{page.stem}.md says '{phrase}' and then names {len(named)}: {sorted(named)}"
        )


def test_the_variant_count_check_catches_a_stale_count() -> None:
    """No page states a variant count today — `csv.md` was rewritten to let the table do
    the counting — so without this control the check above is indistinguishable from one
    that cannot fire. This is the sentence shape that shipped wrong.
    """
    stale = (
        "Three variants carry ten rows each: `csv/people-10-semicolon.csv` uses semicolons;\n"
        "`csv/people-10-quoted-newlines.csv` has a newline in a field;\n"
        "`csv/people-10-quoted-commas.csv` has a comma in one; and\n"
        "`csv/people-10-utf8-bom.csv` starts with a byte-order mark.\n"
    )
    assert [(stated, len(named)) for _phrase, stated, named in variant_claims(stale)] == [(3, 4)]
    fixed = stale.replace("Three", "Four")
    assert all(stated == len(named) for _phrase, stated, named in variant_claims(fixed))


def test_every_fixture_path_the_content_names_exists() -> None:
    named: set[str] = set()
    for page in CONTENT.rglob("*.md"):
        named |= named_paths(page.read_text(encoding="utf-8"))
    assert len(named) > 100, "empty-set control: the pattern must find the named paths"
    assert sorted(named - active_paths()) == []


#: The parsers guide sorts broken files by what a reader must do with them; each heading
#: is held to the outcome the file's own manifest entry measured.
OUTCOME_HEADINGS = {
    "Files that must fail": "must-fail",
    "Files that may be recovered": "may-recover",
    "Files readers disagree on": "varies",
}
MARKER = re.compile(r"^<!-- file: (\S+) -->$")


def misfiled(text: str, outcomes: dict[str, str]) -> list[str]:
    """Broken files on the parsers guide that sit under no heading, or the wrong one."""
    problems: list[str] = []
    heading = ""
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
        elif (found := MARKER.match(line)) and found.group(1) in outcomes:
            path = found.group(1)
            if OUTCOME_HEADINGS.get(heading) != outcomes[path]:
                problems.append(f"{path} ({outcomes[path]}) is under '{heading}'")
    return problems


def edge_outcomes() -> dict[str, str]:
    document = json.loads((ROOT / "manifest.json").read_text())
    return {
        e["path"]: e["props"]["outcome"]
        for e in document["fixtures"]
        if e["format"] == "edge" and e.get("status", "active") == "active"
    }


def test_each_broken_file_on_the_parsers_guide_sits_under_its_measured_outcome() -> None:
    text = (CONTENT / "testing" / "parsers.md").read_text(encoding="utf-8")
    listed = {m.group(1) for line in text.splitlines() if (m := MARKER.match(line))}
    outcomes = edge_outcomes()
    assert {
        "edge/json-trailing-comma.json",
        "edge/zip-truncated-50pct.zip",
        "edge/json-bom.json",
    } <= listed
    assert misfiled(text, outcomes) == []


def test_a_broken_file_under_the_wrong_heading_is_named() -> None:
    wrong = "## Files that must fail\n\n<!-- file: edge/json-bom.json -->\n"
    assert misfiled(wrong, edge_outcomes()) == [
        "edge/json-bom.json (varies) is under 'Files that must fail'"
    ]


EM_DASH = "\u2014"
SITE_COPY = sorted([*CONTENT.rglob("*.md"), *(ROOT / "site" / "templates").glob("*.html")])


def dashed(paths: list[Path]) -> list[str]:
    return [p.name for p in paths if EM_DASH in p.read_text(encoding="utf-8")]


def test_site_copy_has_no_em_dash() -> None:
    names = {p.name for p in SITE_COPY}
    assert {"uploads.md", "edge.md", "languages.md", "format.html"} <= names, "empty-set control"
    assert dashed(SITE_COPY) == []


def test_the_em_dash_check_finds_one(tmp_path: Path) -> None:
    clean, marked = tmp_path / "clean.md", tmp_path / "marked.md"
    clean.write_text("A colon: here.\n", encoding="utf-8")
    marked.write_text(f"A dash {EM_DASH} here.\n", encoding="utf-8")
    assert dashed([clean, marked]) == ["marked.md"]


def test_the_legal_pages_have_no_em_dash() -> None:
    """They render from docs/13's quoted templates, outside `SITE_COPY`: the last exception."""
    when = dt.datetime(2026, 10, 14, tzinfo=dt.UTC)
    bodies = {page.key: str(page.context["body"]) for page in build.legal_pages(ROOT, when)}
    assert {"legal/imprint", "legal/privacy", "legal/terms", "legal/license"} <= set(bodies)
    assert dashed_bodies(bodies) == []


def dashed_bodies(bodies: dict[str, str]) -> list[str]:
    return sorted(key for key, text in bodies.items() if EM_DASH in text)


def test_the_legal_dash_check_finds_one() -> None:
    assert dashed_bodies({"legal/a": "fine", "legal/b": f"a {EM_DASH} b"}) == ["legal/b"]
