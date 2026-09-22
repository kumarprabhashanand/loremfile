"""M4.1: the site, built from this repository (docs/07, docs/12 §2)."""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import struct
import zlib
from collections.abc import Callable
from pathlib import Path

import pytest

from loremfile.infra import locks
from loremfile.site import build, checks, icons, legal, routes

ROOT = Path(__file__).resolve().parents[2]
WHEN = dt.datetime(2026, 9, 15, 12, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("built") / "site"
    build.build(out, root=ROOT, committed=WHEN)
    return out


@pytest.fixture(scope="module")
def keys(site: Path) -> dict[str, Path]:
    return routes.site_files(site)


def fixtures() -> set[str]:
    return {e["path"] for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}


def text(site: Path, key: str) -> str:
    return (site / routes.disk_path(key)).read_text(encoding="utf-8")


def test_the_checks_see_the_whole_site(keys: dict[str, Path]) -> None:
    """Empty-set control first: every check below passes over no pages at all."""
    formats = {e.split("/", 1)[0] for e in fixtures()}
    pages = {key for key in keys if routes.is_page(key)}
    assert formats <= pages
    assert {
        "index.html",
        "formats",
        "docs",
        "docs/faq",
        "legal",
        "legal/imprint",
        "status",
    } <= pages


def test_every_built_key_is_what_its_public_path_reaches(keys: dict[str, Path]) -> None:
    """A key the edge rewrites elsewhere is published and unreachable: a 404 in production
    and a green build. `key_for` mirrors the committed rewrite rules (test_site_routes)."""
    kinds = {"index.html", "legal/imprint", "_formats/pdf.json", routes.AGENT_SKILLS_INDEX_KEY}
    assert kinds <= set(keys), "control: every kind of key is in the build"
    unreachable = {
        key: routes.key_for(routes.public_path(key))
        for key in keys
        if routes.key_for(routes.public_path(key)) != key
    }
    assert unreachable == {}


def test_the_built_site_passes_every_post_build_check(site: Path) -> None:
    assert checks.all_problems(site, fixtures()) == []


def test_building_twice_from_one_commit_gives_identical_bytes(site: Path, tmp_path: Path) -> None:
    """The daily defacement check compares production with a rebuild (docs/09 §3.3)."""
    again = tmp_path / "site"
    build.build(again, root=ROOT, committed=WHEN)
    first, second = routes.site_files(site), routes.site_files(again)
    assert first.keys() == second.keys()
    assert [key for key in first if first[key].read_bytes() != second[key].read_bytes()] == []


def test_no_site_key_sits_under_a_locked_prefix(keys: dict[str, Path]) -> None:
    prefixes = [rule["prefix"] for rule in locks.committed_rules() if rule.get("enabled")]
    assert "pdf/" in prefixes
    assert [key for key in keys if any(key.startswith(prefix) for prefix in prefixes)] == []


def test_the_legal_placeholders_live_in_exactly_the_two_legal_keys(site: Path) -> None:
    """Full tokens: the changelog quotes `%%IMPRINT_*%%` as documentation, and must."""
    assert sorted(legal.leftover_placeholders(site)) == sorted(routes.LEGAL_KEYS)
    assert all(token.startswith("%%IMPRINT_") for token in legal.PLACEHOLDERS.values())


def test_the_legal_pages_stay_out_of_every_index(site: Path) -> None:
    for key in ("sitemap.xml", "llms.txt", "llms-full.txt", "search-index.json"):
        assert "legal/imprint" not in text(site, key) and "legal/privacy" not in text(site, key)
    for key in routes.LEGAL_KEYS:
        page = text(site, key)
        assert f'<meta name="robots" content="{routes.LEGAL_ROBOTS}">' in page
        assert "application/ld+json" not in page
    # Controls: the other legal pages are listed and indexable.
    assert "https://loremfile.dev/legal/license" in text(site, "sitemap.xml")
    assert '<meta name="robots"' not in text(site, "legal/license")


def test_every_page_links_impressum_and_privacy_in_its_footer(
    site: Path, keys: dict[str, Path]
) -> None:
    """One click from every page, labelled exactly "Impressum" (docs/07 §2, 2026-09-21).

    The header copies were dropped; this pins what § 18 Abs. 1 MStV
    and BGH I ZR 228/03 depend on — a permanent link, reachable in one step, with the exact
    label — rather than the position the old test asserted.
    """
    pages = [key for key in keys if routes.is_page(key)]
    # Empty-set control first: every assertion below is vacuous if no page was found.
    assert {"index.html", "legal/imprint", "legal/privacy", "pdf"} <= set(pages), pages[:10]
    for key in pages:
        footer = text(site, key).split("<footer", 1)[1]
        assert '<a href="/legal/imprint">Impressum</a>' in footer, key
        assert '<a href="/legal/privacy">Privacy</a>' in footer, key


def _luminance(hex_colour: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(fg: str, bg: str) -> float:
    lighter, darker = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_the_footer_link_keeps_the_size_and_contrast_the_law_depends_on() -> None:
    """The case-law risk (OLG Frankfurt) is a link in very small or pale type, not its
    position — so a restyle that shrinks or fades the footer link must fail CI here, not
    pass silently. Values measured on production 2026-09-21 (docs/07 §2)."""
    css = (ROOT / "site" / "static" / "site.css").read_text(encoding="utf-8")
    light = css.split("@media (prefers-color-scheme: dark)", 1)[0]
    dark = css.split("@media (prefers-color-scheme: dark)", 1)[1].split("}\n}", 1)[0]

    def token(block: str, name: str) -> str:
        match = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", block)
        assert match, f"--{name} not found"
        return match.group(1).lower()

    assert token(light, "accent") == "#1d4ed8" and token(light, "bg") == "#ffffff"
    assert token(dark, "accent") == "#93c5fd" and token(dark, "bg") == "#0b1120"
    assert round(_contrast(token(light, "accent"), token(light, "bg")), 1) == 6.7
    assert round(_contrast(token(dark, "accent"), token(dark, "bg")), 1) == 10.4

    # Anchored to a line start: `.site-header, main, .site-footer { … }` is a shared layout
    # rule that comes first and carries no font-size, so an unanchored match reads it.
    footer = re.search(r"(?m)^\.site-footer\s*\{([^}]*)\}", css)
    assert footer and "font-size: 0.9rem" in footer.group(1), "footer type size changed"
    assert re.search(r"(?m)^a\s*\{[^}]*color:\s*var\(--accent\)", css), "links lost --accent"
    # Nothing may restyle the footer's links more specifically than the rules above.
    assert not re.search(r"\.site-footer[^{]*\ba\b[^{]*\{", css), "a footer-link override"


def test_robots_txt_is_the_one_docs_04_specifies(site: Path) -> None:
    section = (
        (ROOT / "docs" / "04-manifest-and-discovery.md").read_text().split("## 6. `robots.txt`")[1]
    )
    match = re.search(r"```\n(.*?)```", section, re.S)
    assert match is not None
    assert text(site, "robots.txt") == match.group(1)


def test_the_only_dates_come_from_the_commit(site: Path) -> None:
    assert "Expires: 2027-09-15T12:00:00Z\n" in text(site, ".well-known/security.txt")
    assert set(re.findall(r"<lastmod>([^<]+)</lastmod>", text(site, "sitemap.xml"))) == {
        "2026-09-15"
    }


def test_a_format_index_has_the_manifest_shape_for_one_format(site: Path) -> None:
    index = json.loads(text(site, "_formats/pdf.json"))
    manifest = json.loads((ROOT / "manifest.json").read_text())
    active = [
        e for e in manifest["fixtures"] if e["format"] == "pdf" and e.get("status") == "active"
    ]
    assert set(index) == set(manifest) - {"formats"}
    assert index["fixtures"] == active
    assert index["count"] == len(active)
    assert index["total_bytes"] == sum(e["bytes"] for e in active)


def test_copied_discovery_files_are_the_repositorys_bytes(site: Path) -> None:
    for key in ("manifest.json", "formats.json", "sha256sums.txt"):
        assert (site / key).read_bytes() == (ROOT / key).read_bytes()


def test_the_mark_is_inlined_and_assets_are_content_hashed(
    site: Path, keys: dict[str, Path]
) -> None:
    home = text(site, "index.html")
    assert '<svg aria-hidden="true"' in home
    assert "<object" not in home and "<iframe" not in home
    css = [key for key in keys if re.fullmatch(r"assets/site\.[0-9a-f]{12}\.css", key)]
    assert len(css) == 1
    assert f'href="/{css[0]}"' in home


def test_the_popular_list_links_every_path(site: Path) -> None:
    home = text(site, "index.html")
    assert all(f'href="/{path}"' in home for path in build.POPULAR)


def test_the_icons_have_the_documented_sizes(site: Path) -> None:
    def png_size(data: bytes) -> tuple[int, int]:
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", data[16:24])
        return width, height

    assert png_size((site / "assets/og.png").read_bytes()) == (1200, 630)
    assert png_size((site / "apple-touch-icon.png").read_bytes()) == (180, 180)
    assert struct.unpack("<HHH", (site / "favicon.ico").read_bytes()[:6]) == (0, 1, 3)


def test_a_png_decodes_to_the_pixels_drawn() -> None:
    canvas = icons.Canvas(3, 2, (1, 2, 3))
    canvas.fill(1, 0, 1, 1, (9, 9, 9))
    data = canvas.png()
    raw = zlib.decompress(data[data.index(b"IDAT") + 4 : data.index(b"IEND") - 8])
    assert raw == b"\x00" + bytes([1, 2, 3, 9, 9, 9, 1, 2, 3]) + b"\x00" + bytes([1, 2, 3] * 3)


def _append(snippet: str) -> Callable[[str], str]:
    return lambda page: page.replace("</main>", f"{snippet}</main>")


@pytest.mark.parametrize(
    ("key", "change", "expected"),
    [
        ("formats", _append("<h1>again</h1>"), "2 <h1> elements"),
        ("formats", _append('<a href="https://example.com/">x</a>'), "outside the allow-list"),
        ("formats", _append('<a href="http://loremfile.dev/pdf">x</a>'), "neither https"),
        ("formats", _append('<a href="/pdf/nothing.pdf">x</a>'), "resolves to no key"),
        ("formats", _append("</span>"), "does not parse"),
        (
            "legal/imprint",
            lambda page: page.replace('name="robots"', 'name="x"'),
            "robots meta tag missing",
        ),
        (
            "legal/license",
            lambda page: page.replace(
                "<title>", f'<meta name="robots" content="{routes.LEGAL_ROBOTS}"><title>'
            ),
            "robots meta tag present",
        ),
        (
            "sitemap.xml",
            lambda page: page.replace(
                "</urlset>", "<url><loc>https://loremfile.dev/legal/privacy</loc></url></urlset>"
            ),
            "lists /legal/privacy",
        ),
        (
            "llms.txt",
            lambda page: page + "- https://loremfile.dev/legal/imprint\n",
            "lists a legal page",
        ),
        (
            ".well-known/security.txt",
            lambda page: page.replace("Expires: ", "Expiry: "),
            "no Expires",
        ),
    ],
    ids=[
        "second h1",
        "external link",
        "insecure link",
        "dangling link",
        "invalid html",
        "legal page without robots meta",
        "robots meta on an indexable page",
        "legal page in the sitemap",
        "legal page in llms.txt",
        "security.txt without Expires",
    ],
)
def test_each_check_fails_when_its_rule_is_broken(
    site: Path, tmp_path: Path, key: str, change: Callable[[str], str], expected: str
) -> None:
    """Negative controls: a check nobody has watched fail proves nothing (AGENTS.md)."""
    copy = tmp_path / "site"
    shutil.copytree(site, copy)
    path = copy / routes.disk_path(key)
    path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")
    problems = checks.all_problems(copy, fixtures())
    assert any(expected in problem for problem in problems), problems
