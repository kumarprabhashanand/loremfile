"""A page a visitor can use in ten seconds (2026-11-13): Start here, the home page's order,
plural counts, the card, and the README and Dependabot lines that must not drift.

Every guard has a control that shows it firing: a smaller file that is `expected_drift` must
not be chosen, a count of one must not read plural, and the README's old claim must be caught.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest
import yaml

from loremfile.catalog import Catalog
from loremfile.manifest import alias_original
from loremfile.site import build, defaults, icons
from loremfile.site.build import POPULAR, key_props

ROOT = Path(__file__).resolve().parents[2]
WHEN = dt.datetime(2026, 9, 15, 12, 0, tzinfo=dt.UTC)
CATALOG = Catalog.load()
MANIFEST = json.loads((ROOT / "manifest.json").read_text())["fixtures"]
DRIFTING = {f.path for fmt in CATALOG.formats for f in fmt.fixtures if f.expected_drift}
FAMILY = {fmt.format: fmt.family.value for fmt in CATALOG.formats}
DOCS = (ROOT / "docs" / "05-fixture-catalog.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("start-here") / "site"
    build.build(out, root=ROOT, committed=WHEN)
    return out


def page(site: Path, fmt: str) -> str:
    return (site / f"{fmt}.html").read_text(encoding="utf-8")


def choice(fmt: str) -> tuple[str, str] | None:
    return defaults.default_choice(fmt, FAMILY[fmt], MANIFEST, DRIFTING, POPULAR)


def entry(path: str, size: int, **extra: Any) -> dict[str, Any]:
    return {"path": path, "format": path.split("/", maxsplit=1)[0], "bytes": size, **extra}


# --- which file a format starts with ---------------------------------------------------------


def test_the_defaults_are_found_where_they_are_known_to_be() -> None:
    """Every check below holds of an empty set, so name specifics first."""
    assert choice("pdf") == ("pdf/a4-3pages.pdf", "popular")
    assert choice("mp4") == ("mp4/720p-5s.mp4", "popular")
    assert choice("webm") == ("webm/720p-5s-vp8.webm", "smallest"), "its VP9 file is expected_drift"
    assert choice("gif") == ("gif/static-256x256.gif", "override")
    assert len([f for f in FAMILY if choice(f)]) == 75


def test_no_default_is_a_file_only_the_ci_fleet_reproduces_or_a_broken_one() -> None:
    by_path = {e["path"]: e for e in MANIFEST}
    assert len(DRIFTING) == 11, "control: the exclusion has something to exclude"
    for fmt in FAMILY:
        found = choice(fmt)
        if found is None:
            continue
        path, _ = found
        assert path not in DRIFTING, path
        assert not by_path[path].get("edge_case"), path
        assert not by_path[path].get("supersededBy"), path
        assert by_path[path].get("status", "active") == "active", path


def test_a_format_with_no_ordinary_file_has_no_default() -> None:
    nones = sorted(fmt for fmt in FAMILY if choice(fmt) is None)
    assert nones == ["edge", "hls", "ogv", "opus", "ts"], "collections, drift, and files over 2 MB"
    sizes = {e["path"]: e["bytes"] for e in MANIFEST}
    for fmt in ("ogv", "ts"):
        assert all(sizes[e["path"]] >= defaults.MEDIA_LIMIT for e in MANIFEST if e["format"] == fmt)
    assert {p for p in DRIFTING if p.startswith("opus/")} == {
        e["path"] for e in MANIFEST if e["format"] == "opus"
    }


def test_the_rule_on_entries_a_smaller_drifting_or_broken_file_is_never_chosen() -> None:
    plain = entry("txt/b.txt", 500)
    smaller = [
        entry("txt/a.txt", 10),
        entry("txt/c.txt", 20, edge_case=True),
        entry("txt/d.txt", 30, supersededBy="txt/b.txt"),
        entry("txt/e.txt", 40, status="removed"),
    ]
    pick = defaults.default_choice("txt", "text", [plain, *smaller], {"txt/a.txt"}, ())
    assert pick == ("txt/b.txt", "smallest")
    # Control: with nothing excluded, the smallest is simply the smallest.
    assert defaults.default_choice("txt", "text", [plain, smaller[0]], set(), ()) == (
        "txt/a.txt",
        "smallest",
    )
    # Popular beats smaller; a popular file that drifts does not count as popular.
    assert defaults.default_choice("txt", "text", [plain, smaller[0]], set(), ("txt/b.txt",)) == (
        "txt/b.txt",
        "popular",
    )
    assert defaults.default_choice(
        "txt", "text", [plain, smaller[0]], {"txt/b.txt"}, ("txt/b.txt",)
    ) == (
        "txt/a.txt",
        "smallest",
    )


def test_a_media_default_is_under_two_megabytes_or_there_is_none() -> None:
    big, small = entry("mp3/big.mp3", 3_000_000), entry("mp3/small.mp3", 1_900_000)
    assert defaults.default_choice("mp3", "audio", [big, small], set(), ()) == (
        "mp3/small.mp3",
        "smallest",
    )
    # Popular does not exempt a media file from the limit.
    assert defaults.default_choice("mp3", "audio", [big, small], set(), ("mp3/big.mp3",)) == (
        "mp3/small.mp3",
        "smallest",
    )
    # Nothing under the limit: no default, rather than a heavy one.
    assert defaults.default_choice("mp3", "audio", [big], set(), ()) is None
    # Control: the same two sizes in a format that is not media have no limit.
    csvs = [entry("csv/big.csv", 3_000_000), entry("csv/small.csv", 2_500_000)]
    assert defaults.default_choice("csv", "data", csvs, set(), ())[0] == "csv/small.csv"
    assert defaults.default_choice("csv", "data", csvs[:1], set(), ())[0] == "csv/big.csv"
    sizes = {e["path"]: e["bytes"] for e in MANIFEST}
    for fmt, family in FAMILY.items():
        found = choice(fmt)
        if family in defaults.MEDIA_FAMILIES and found:
            assert sizes[found[0]] < defaults.MEDIA_LIMIT, fmt


def test_every_override_is_eligible_and_changes_the_answer(monkeypatch) -> None:
    by_path = {e["path"]: e for e in MANIFEST}
    for fmt, (path, reason) in dict(defaults.OVERRIDES).items():
        assert reason and path in by_path and path not in DRIFTING
        assert defaults.default_choice(fmt, FAMILY[fmt], MANIFEST, DRIFTING, ()) == (
            path,
            "override",
        )
        with monkeypatch.context() as patch:
            patch.setattr(defaults, "OVERRIDES", {})
            plain = defaults.default_choice(fmt, FAMILY[fmt], MANIFEST, DRIFTING, ())
        assert plain is not None and plain[0] != path, f"{fmt}: the override changes nothing"
    with pytest.raises(ValueError, match="not eligible"):
        defaults.default_choice("gif", "images", [entry("gif/a.gif", 1)], set(), ())


def test_the_table_in_docs_05_is_what_the_code_chooses() -> None:
    rows = re.findall(r"^\| `([a-z0-9]+)` \| `([^`]+)` \| ([^|]+) \|$", DOCS, re.MULTILINE)
    documented = {fmt: (path, basis) for fmt, path, basis in rows}
    assert len(documented) == 75 and documented["pdf"][0] == "pdf/a4-3pages.pdf"
    for fmt in FAMILY:
        found = choice(fmt)
        if found is None:
            assert fmt not in documented, fmt
            continue
        path, basis = found
        assert documented[fmt][0] == path, fmt
        assert (documented[fmt][1].strip() == basis) or basis == "override", fmt


# --- the page -------------------------------------------------------------------------------


def test_a_format_page_opens_with_a_url_to_copy_and_a_file_to_download(site: Path) -> None:
    html = page(site, "pdf")
    assert html.index("Start here") < html.index('class="prose intro"'), "above the guide"
    block = html.split('<section class="start"', 1)[1].split("</section>", 1)[0]
    assert "<code>https://loremfile.dev/pdf/sample.pdf</code>" in block, "the alias is the URL"
    assert 'data-copy="https://loremfile.dev/pdf/sample.pdf"' in block
    assert re.search(r'<a class="download" href="/pdf/sample\.pdf" download>', block)
    assert "same bytes as" in block.lower() and "pdf/a4-3pages.pdf" in block, "and whose bytes"
    assert "https://" not in re.search(r'href="([^"]*)" download', block).group(1)


@pytest.mark.parametrize(
    ("fmt", "element"),
    [
        ("png", '<img class="preview"'),
        ("mp3", '<audio class="preview" controls preload="none"'),
        ("mp4", '<video class="preview" controls preload="none"'),
        ("pdf", None),
        ("tiff", None),
        ("mkv", None),
    ],
)
def test_a_preview_only_where_a_browser_draws_or_plays_the_file(site, fmt, element) -> None:
    html = page(site, fmt)
    assert 'class="preview"' in html or 'class="preview" ' in html or element is None
    if element is None:
        assert "preview" not in html.split('<section class="start"', 1)[1].split("</section>")[0]
    else:
        assert element in html
    if fmt == "png":
        assert 'loading="lazy"' in html.split('<img class="preview"', 1)[1].split(">", 1)[0]


def test_the_preview_element_follows_the_formats_kind_everywhere(site: Path) -> None:
    kinds = {"image": "<img ", "audio": "<audio ", "video": "<video "}
    for fmt in FAMILY:
        found = choice(fmt)
        html = page(site, fmt)
        if found is None:
            assert 'class="start"' not in html, f"{fmt} has no default and no block"
            continue
        block = html.split('<section class="start"', 1)[1].split("</section>", 1)[0]
        kind = defaults.PREVIEW.get(fmt)
        for name, tag in kinds.items():
            assert (tag in block) == (name == kind), (fmt, name)
        if kind in {"audio", "video"}:
            assert 'preload="none"' in block, "nothing is fetched until the visitor asks"


def test_every_table_row_has_a_download_link(site: Path) -> None:
    html = page(site, "pdf")
    table = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    rows = re.findall(r"<tr>", table)
    downloads = re.findall(r'<a class="download" href="/[^"]+" download>Download</a>', table)
    assert len(rows) == len(downloads) > 10


# --- the home page ---------------------------------------------------------------------------


def test_the_home_page_leads_with_the_example_then_search_and_the_grid_then_the_rest(
    site: Path,
) -> None:
    html = (site / "index.html").read_text(encoding="utf-8")
    order = [
        "<h1>",
        "You are testing something that takes files",
        "Here is one:",
        "<code>https://loremfile.dev/pdf/sample.pdf</code>",
        "Paste it into a browser",
        'id="search-heading"',
        'id="formats-heading"',
        "The files are CC0, so copying one into your own repository is fine.",
        "Want to fetch files from code? There are four ways:",
        "We check the live site from outside every day.",
        'id="tasks-heading"',
    ]
    positions = [html.index(marker) for marker in order]
    assert positions == sorted(positions), order
    example = html.split('<p class="example">', 1)[1].split("</p>", 1)[0]
    assert 'data-copy="https://loremfile.dev/pdf/sample.pdf"' in example


def test_the_paragraphs_that_moved_below_the_grid_kept_their_words() -> None:
    below = build.home_parts((ROOT / "site/content/home.md").read_text(encoding="utf-8"))[2]
    for words in (
        "The files are CC0, so copying one into your own repository is fine. Each has a SHA-256 "
        "in our\nmanifest, and your test can compare it with what it downloaded. A published URL "
        "never changes\nits bytes, so a hash you save today still matches next month.",
        "- **[Action](https://github.com/kumarprabhashanand/loremfile/tree/main/action)** is for",
        "- **[MCP](/docs/mcp)** is for agents.",
        "We check the live site from outside every day.",
    ):
        assert words in below, words
    with pytest.raises(build.SiteError, match="needs exactly one"):
        build.home_parts("no markers at all")


def test_the_example_is_a_published_file() -> None:
    assert build.EXAMPLE in {e["path"] for e in MANIFEST}
    assert f"loremfile.dev/{build.EXAMPLE}" == icons.OG_URL, "the card shows the home example"
    assert alias_original(next(e for e in MANIFEST if e["path"] == build.EXAMPLE)) == POPULAR[0]


# --- counts read as one or many --------------------------------------------------------------


def test_a_count_of_one_reads_singular_wherever_a_page_counts() -> None:
    assert key_props({"pages": 1}) == "1 page"
    assert key_props({"pages": 3}) == "3 pages"
    assert key_props({"slides": 1}) == "1 slide"
    assert key_props({"sheets": 1, "rows": 1}) == "1 sheet, 1 row"
    assert key_props({"chapters": 1}) == "1 chapter"
    assert key_props({"segments": 1}) == "1 segment"
    assert key_props({"animated": True, "frames": 1}) == "1 frame"
    assert key_props({"animated": True, "frames": 10}) == "10 frames"
    assert key_props({"animated": True}) == "animated", "no frame count, no 'None frames'"
    assert key_props({"rows": 1000}) == "1,000 rows"
    # Control: the interpolation this replaced.
    assert f"{1} {'pages'}" == "1 pages"


SINGULAR_ONLY = re.compile(
    r"(?<![\w.,-])1 (pages|slides|sheets|chapters|segments|features|rows|frames|files|formats|"
    r"entries|channels|lines|columns|words|bytes|renditions|paragraphs|variants)\b"
)


def test_no_built_page_says_one_of_a_plural(site: Path) -> None:
    assert SINGULAR_ONLY.search("pdf: 1 pages, 4 files") and SINGULAR_ONLY.search("1 bytes")
    assert not SINGULAR_ONLY.search("1 page, 10 pages, 1,000 rows, 21 files")
    scanned, found = 0, []
    for path in sorted(site.rglob("*")):
        if path.suffix in {".html", ".md", ".txt", ".json", ".xml"} and path.is_file():
            scanned += 1
            for match in SINGULAR_ONLY.finditer(path.read_text(encoding="utf-8", errors="ignore")):
                found.append((path.relative_to(site).as_posix(), match.group(0)))
    assert scanned > 200 and "1 page" in page(site, "pdf"), "the sweep saw the pages"
    assert not found, found[:10]


# --- the card ---------------------------------------------------------------------------------


def pixels(png: bytes) -> list[bytes]:
    """The rows of an 8-bit RGB PNG with no filtering, which is how `icons` writes them."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    data, offset = b"", 8
    while offset < len(png):
        (size,) = struct.unpack(">I", png[offset : offset + 4])
        if png[offset + 4 : offset + 8] == b"IDAT":
            data += png[offset + 8 : offset + 8 + size]
        offset += 12 + size
    raw = zlib.decompress(data)
    stride = 1 + width * 3
    assert len(raw) == stride * height
    return [raw[row * stride + 1 : (row + 1) * stride] for row in range(height)]


def test_the_card_draws_the_tagline_and_the_example_beside_the_mark() -> None:
    rows = pixels(icons.og_card())
    ink = bytes(icons.INK)
    url = bytes(icons.URL_INK)

    def has(color: bytes, top: int, bottom: int) -> bool:
        return any(color in row[400 * 3 :] for row in rows[top:bottom])

    assert has(ink, 320, 348), "the tagline's band holds ink"
    assert has(url, 385, 420), "the example URL's band holds its colour"
    assert not has(url, 320, 348), "control: the colours are not the same band"
    # Every glyph the card needs exists, and nothing runs past the edge.
    for text in (icons.OG_TAGLINE, icons.OG_URL, "loremfile.dev"):
        assert set(text) <= set(icons.GLYPHS), set(text) - set(icons.GLYPHS)
    assert 400 + max(len(icons.OG_TAGLINE), len(icons.OG_URL)) * 24 <= 1200 - 40
    with pytest.raises(KeyError):
        icons.draw_text(icons.Canvas(10, 10, icons.PAPER), "Q", 0, 0, 1, icons.INK)


# --- what the README and Dependabot must not say or do ---------------------------------------

README_COUNT = re.compile(r"\b\d[\d,]* (?:files|formats|fixtures)\b|catalog version \d")


def test_the_readme_states_no_count_of_files_formats_or_a_version() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "loremfile.dev/manifest.json" in readme and "Canonical host" in readme
    assert not README_COUNT.findall(readme), README_COUNT.findall(readme)
    assert 'catalog-version: "' not in readme, "an example pin drifts like a count"
    # Control: the sentence this replaced.
    assert README_COUNT.search(
        "228 files across 78 formats plus the edge/ set, at catalog version 1.2.0"
    )


def test_dependabot_runs_monthly_for_all_three_ecosystems() -> None:
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    updates = {u["package-ecosystem"]: u["schedule"]["interval"] for u in config["updates"]}
    assert updates == {"pip": "monthly", "github-actions": "monthly", "docker": "monthly"}
    runbook = (ROOT / "docs/11-operations-runbook.md").read_text(encoding="utf-8")
    assert "One maintenance pull request" in runbook and "No standalone pull request" in runbook
