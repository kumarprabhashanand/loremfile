"""M4.1: the site, built from this repository (docs/07, docs/12 §2)."""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import shutil
import struct
import zlib
from collections.abc import Callable
from pathlib import Path

import pytest

from loremfile.infra import locks, purge
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
    pass silently. Values computed from the 2026-10 palette tokens (docs/07 §2)."""
    css = (ROOT / "site" / "static" / "site.css").read_text(encoding="utf-8")
    light = css.split("@media (prefers-color-scheme: dark)", 1)[0]
    dark = css.split("@media (prefers-color-scheme: dark)", 1)[1].split("}\n}", 1)[0]

    def token(block: str, name: str) -> str:
        match = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", block)
        assert match, f"--{name} not found"
        return match.group(1).lower()

    assert token(light, "accent") == "#0f5e59" and token(light, "bg") == "#fbfaf7"
    assert token(dark, "accent") == "#6fc4bb" and token(dark, "bg") == "#16140f"
    assert round(_contrast(token(light, "accent"), token(light, "bg")), 1) == 7.3
    assert round(_contrast(token(dark, "accent"), token(dark, "bg")), 1) == 9.0

    # Anchored to a line start: `.site-header, main, .site-footer { … }` is a shared layout
    # rule that comes first and carries no font-size, so an unanchored match reads it.
    footer = re.search(r"(?m)^\.site-footer\s*\{([^}]*)\}", css)
    assert footer and "font-size: 0.9rem" in footer.group(1), "footer type size changed"
    assert re.search(r"(?m)^a\s*\{[^}]*color:\s*var\(--accent\)", css), "links lost --accent"
    # Nothing may restyle the footer's links more specifically than the rules above.
    assert not re.search(r"\.site-footer[^{]*\ba\b[^{]*\{", css), "a footer-link override"


#: Selectors for the controls a person operates: their borders are UI, held to 3:1.
CONTROL = re.compile(r"\b(input|button|select|textarea)\b")


def border_misuse(css: str) -> list[str]:
    """Controls bordered with anything but --muted, and --line used anywhere but a border."""
    problems: list[str] = []
    for raw, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        selector = " ".join(raw.split())
        control = bool(CONTROL.search(selector))
        for prop, value in re.findall(r"([\w-]+)\s*:\s*([^;]+)", body):
            border = prop.startswith("border")
            if "var(--line)" in value and (not border or control):
                problems.append(f"{selector}: {prop} uses --line")
            if control and border and "var(" in value and "var(--muted)" not in value:
                problems.append(f"{selector}: {prop} is not --muted")
    return problems


def test_controls_are_bordered_with_muted_and_line_is_decoration_only() -> None:
    css = (ROOT / "site" / "static" / "site.css").read_text(encoding="utf-8")
    assert {".search-box input", "button.copy"} <= {
        " ".join(s.split()) for s in re.findall(r"([^{}]+)\{", css)
    }, "empty-set control: the controls are in the stylesheet"
    assert border_misuse(css) == []


def test_the_border_check_fires() -> None:
    assert border_misuse("button.copy { border: 1px solid var(--line); }") == [
        "button.copy: border uses --line",
        "button.copy: border is not --muted",
    ]
    assert border_misuse(".family { color: var(--line); }") == [".family: color uses --line"]


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


def test_the_home_page_names_hotlinking_before_downloading(site: Path) -> None:
    """docs/07 §6: downloading is named after hotlinking, never before it."""
    home = text(site, "index.html")
    places = {
        "title": re.search(r"<title>(.*?)</title>", home),
        "description": re.search(r'<meta name="description" content="([^"]*)"', home),
        "first line": re.search(r'<div class="pitch">\s*<p>(.*?)</p>', home, re.S),
    }
    for where, found in places.items():
        assert found is not None, f"the home page has no {where}"
        words = found.group(1).lower()
        assert "hotlink" in words and "download" in words, (where, words)
        assert words.index("hotlink") < words.index("download"), (where, words)
    assert len(places["description"].group(1)) < 160  # type: ignore[union-attr]


def test_the_home_page_names_four_routes_and_links_status(site: Path) -> None:
    home = text(site, "index.html")
    routes_ = {
        "Action": "https://github.com/kumarprabhashanand/loremfile/tree/main/action",
        "pip": "https://pypi.org/project/loremfile/",
        "npm": "https://www.npmjs.com/package/loremfile",
        "MCP": "/docs/mcp",
    }
    for name, href in routes_.items():
        assert f'<strong><a href="{href}">{name}</a></strong>' in home, name
    assert 'href="/status"' in home


def test_the_mcp_page_has_both_configs_the_tools_and_the_registry(site: Path) -> None:
    page = text(site, "docs/mcp")
    plain = html.unescape(page)
    assert '"command": "npx", "args": ["-y", "loremfile", "mcp"]' in plain
    assert '"command": "uvx", "args": ["loremfile", "mcp"]' in plain
    shipped = json.loads((ROOT / "client" / "src" / "loremfile_client" / "tools.json").read_text())
    assert [tool["name"] for tool in shipped] == [
        "list_fixtures",
        "describe_fixture",
        "verify_file",
    ]
    assert all(f"<code>{tool['name']}</code>" in page for tool in shipped)
    assert (
        'href="https://registry.modelcontextprotocol.io/v0/servers?search=io.github.kumarprabhashanand/loremfile"'
        in page
    )


def test_both_llms_files_point_agents_at_the_mcp_server(site: Path) -> None:
    for key in ("llms.txt", "llms-full.txt"):
        body = text(site, key)
        assert "uvx loremfile mcp" in body and "https://loremfile.dev/docs/mcp" in body, key


def test_every_format_page_names_the_command_for_its_whole_format(site: Path) -> None:
    formats = {path.split("/", 1)[0] for path in fixtures()}
    assert {"pdf", "csv", "png", "edge"} <= formats, "empty-set control"
    for fmt in sorted(formats):
        assert f"<code>npx loremfile get --format {fmt}</code>" in text(site, fmt), fmt


def test_a_lead_line_shows_only_what_the_manifest_measured() -> None:
    wav = {
        "path": "wav/a.wav",
        "bytes": 529244,
        "mime": "audio/wav",
        "props": {"duration_ms": 3000, "acodec": "pcm_s16le", "sample_rate": 44100, "channels": 1},
    }
    assert build.file_facts(wav) == (
        "[`https://loremfile.dev/wav/a.wav`](/wav/a.wav) · 529.2 KB (529,244 bytes) · "
        "`audio/wav` · 3 s · pcm_s16le · 44.1 kHz · 1 channel"
    )
    small = {
        "path": "png/b.png",
        "bytes": 920,
        "mime": "image/png",
        "props": {"width": 4, "height": 2},
    }
    assert build.file_facts(small) == (
        "[`https://loremfile.dev/png/b.png`](/png/b.png) · 920 bytes · `image/png` · 4x2"
    )


def test_a_lead_marker_must_name_a_file_its_page_may_list() -> None:
    active = {"m4a/aac-30s.m4a": {"path": "m4a/aac-30s.m4a", "bytes": 1, "mime": "audio/mp4"}}
    page = "One sentence.\n\n<!-- file: m4a/aac-30s.m4a -->\n\nThe rest.\n"
    assert "(/m4a/aac-30s.m4a)" in build.lead_files(page, "m4a.md", active)
    for wrong in ("mp3/sine-440hz-30s.mp3", "m4a/missing.m4a"):
        with pytest.raises(build.SiteError, match=wrong):
            build.lead_files(page.replace("m4a/aac-30s.m4a", wrong), "m4a.md", active)


def test_a_page_with_a_lead_shows_its_file_right_after_its_opening_sentence(site: Path) -> None:
    entries = {e["path"]: e for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
    checked: set[str] = set()
    for page in sorted((ROOT / "site" / "content" / "formats").glob("*.md")):
        found = build.FILE.search(page.read_text(encoding="utf-8"))
        if found is None:
            continue
        intro = re.search(r'<div class="prose intro">(.*?)</div>', text(site, page.stem), re.S)
        assert intro is not None, page.stem
        second = re.findall(r"<p>(.*?)</p>", intro.group(1), re.S)[1]
        entry = entries[found.group(1)]
        assert f'href="/{entry["path"]}"' in second, page.stem
        assert f"{entry['bytes']:,} bytes" in second, page.stem
        checked.add(page.stem)
    assert {"m4a", "md", "wav"} <= checked, "empty-set control"


def test_the_icons_have_the_documented_sizes(site: Path) -> None:
    def png_size(data: bytes) -> tuple[int, int]:
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", data[16:24])
        return width, height

    assert png_size((site / "assets/og.png").read_bytes()) == (1200, 630)
    assert png_size((site / "apple-touch-icon.png").read_bytes()) == (180, 180)
    assert struct.unpack("<HHH", (site / "favicon.ico").read_bytes()[:6]) == (0, 1, 3)


def theme_tokens() -> tuple[dict[str, str], dict[str, str]]:
    """The light and the dark palette in site/static/site.css."""
    css = (ROOT / "site" / "static" / "site.css").read_text(encoding="utf-8")
    light, rest = css.split("@media (prefers-color-scheme: dark)", 1)
    dark = rest.split("}\n}", 1)[0]
    pattern = r"--([\w-]+):\s*(#[0-9a-fA-F]{6})"
    return (
        {name: value.lower() for name, value in re.findall(pattern, light)},
        {name: value.lower() for name, value in re.findall(pattern, dark)},
    )


#: The mark's square, deliberately not --accent: one colour has to clear 3:1 on both themes'
#: backgrounds and on browser chrome, while link text needs 4.5:1 on one known background
#: (docs/07 §2). Matching it to the accent would bring back 2.42:1 in dark mode.
MARK_SQUARE = "#18887e"


def brand_drift(svg: str, drawn: dict[str, icons.Color], tokens: dict[str, str]) -> list[str]:
    """Where the mark, or the icons and social card drawn from it, leave their colours."""
    expected = [MARK_SQUARE, "#fff", tokens["fg"], tokens["fg"], tokens["fg"]]
    fills = [fill.lower() for fill in re.findall(r'fill="(#[0-9a-fA-F]+)"', svg)]
    problems = [] if fills == expected else [f"mark.svg fills {fills}, expected {expected}"]
    wanted = (("MARK", MARK_SQUARE), ("INK", tokens["fg"]), ("BACKDROP", tokens["code-bg"]))
    for name, want in wanted:
        drawn_hex = "#{:02x}{:02x}{:02x}".format(*drawn[name])
        if drawn_hex != want:
            problems.append(f"icons.{name} is {drawn_hex}, expected {want}")
    return problems


MARK = ROOT / "site" / "static" / "mark.svg"
DRAWN = ("MARK", "INK", "BACKDROP")


def test_the_mark_and_the_drawn_icons_use_the_site_palette() -> None:
    light, _dark = theme_tokens()
    assert {"accent", "fg", "code-bg"} <= set(light), "the token search found the palette"
    drawn = {name: getattr(icons, name) for name in DRAWN}
    assert brand_drift(MARK.read_text(encoding="utf-8"), drawn, light) == []
    assert icons.PAPER == (255, 255, 255)


def test_the_mark_clears_3_to_1_on_both_backgrounds_and_the_accent_would_not() -> None:
    light, dark = theme_tokens()
    assert round(_contrast(MARK_SQUARE, light["bg"]), 2) == 4.14
    assert round(_contrast(MARK_SQUARE, dark["bg"]), 2) == 4.26
    assert round(_contrast(light["accent"], dark["bg"]), 2) == 2.42


def test_the_brand_check_names_a_mark_drawn_in_the_accent() -> None:
    light, _dark = theme_tokens()
    accent, fg = light["accent"], light["fg"]
    svg = MARK.read_text(encoding="utf-8").replace(MARK_SQUARE, accent)
    drawn = {name: getattr(icons, name) for name in DRAWN} | {"MARK": (15, 94, 89)}
    old, new = [accent, "#fff", fg, fg, fg], [MARK_SQUARE, "#fff", fg, fg, fg]
    assert brand_drift(svg, drawn, light) == [
        f"mark.svg fills {old}, expected {new}",
        f"icons.MARK is {accent}, expected {MARK_SQUARE}",
    ]


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


# --- testing guides -------------------------------------------------------------------


def test_each_guide_lists_exactly_the_files_its_prose_names(site: Path) -> None:
    named_any = set()
    for key, _title, _description, source in build.TESTING:
        named = list(
            dict.fromkeys(build.FILE.findall((ROOT / "site/content" / source).read_text()))
        )
        page = text(site, key)
        datasets = [b for b in checks._jsonld(page) if b.get("@type") == "Dataset"]
        assert len(datasets) == 1, key
        urls = [d["contentUrl"] for d in datasets[0]["distribution"]]
        assert urls == [f"https://loremfile.dev/{path}" for path in named], key
        assert all(f'href="/{path}"' in page for path in named), key
        named_any |= set(named)
    assert {"bin/10mb-plus-1.bin", "edge/json-trailing-comma.json", "mp4/50mb.mp4"} <= named_any


def test_the_guides_are_linked_listed_and_indexed(site: Path) -> None:
    keys = [key for key, *_ in build.TESTING]
    assert len(keys) == 3, "control: three guides are named in build.TESTING"
    sitemap = text(site, "sitemap.xml")
    llms_txt = text(site, "llms.txt")
    home = text(site, "index.html")
    index = text(site, "testing")
    for key in keys:
        assert f"<loc>https://loremfile.dev/{key}</loc>" in sitemap, key
        assert f"(https://loremfile.dev/{key})" in llms_txt, key
        assert f'href="/{key}"' in home and f'href="/{key}"' in index, key


def test_a_guide_that_names_an_unpublished_file_stops_the_build(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "site" / "content", tmp_path / "site" / "content")
    guide = tmp_path / "site" / "content" / "testing" / "uploads.md"
    guide.write_text(guide.read_text() + "\n<!-- file: bin/never-published.bin -->\n")
    manifest = build.Manifest.load(ROOT / "manifest.json")
    with pytest.raises(build.SiteError, match=re.escape("bin/never-published.bin")):
        build.testing_pages(tmp_path, manifest, modified=WHEN.date())


# --- superseded entries ---------------------------------------------------------------


def test_a_superseded_file_is_named_but_not_recommended(site: Path) -> None:
    old, new = "jpg/cmyk-640x480.jpg", "jpg/cmyk-640x640.jpg"
    page = text(site, "jpg")
    table, _, after = page.partition('<h2 id="superseded">')
    assert f'href="/{new}"' in table and f'href="/{old}"' not in table
    assert f'href="/{old}"' in after and f'href="/{new}"' in after
    dataset = next(b for b in checks._jsonld(page) if b.get("@type") == "Dataset")
    urls = {d["contentUrl"] for d in dataset["distribution"]}
    assert f"https://loremfile.dev/{new}" in urls and f"https://loremfile.dev/{old}" not in urls
    index = json.loads(text(site, "_formats/jpg.json"))
    served = {e["path"]: e for e in index["fixtures"]}
    assert served[old]["supersededBy"] == new and served[old]["deprecated"] is True
    assert old not in {row["path"] for row in json.loads(text(site, "search-index.json"))}
    assert f"| {old} |" not in text(site, "llms-full.txt") and f"| {new} |" in text(
        site, "llms-full.txt"
    )


def test_a_format_without_supersessions_shows_no_section(site: Path) -> None:
    assert 'id="superseded"' not in text(site, "png")


# --- structured data: sizes, hashes, dates and the formats collection --------------------


def manifest_entries() -> dict[str, dict]:
    return {e["path"]: e for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}


def datasets(site: Path, keys: dict[str, Path]) -> dict[str, dict]:
    found = {}
    for key in keys:
        if routes.is_page(key) and key not in routes.LEGAL_KEYS:
            for block in checks._jsonld(text(site, key)):
                if block.get("@type") == "Dataset":
                    found[key] = block
    return found


def test_every_data_download_carries_the_manifest_size_and_hash(
    site: Path, keys: dict[str, Path]
) -> None:
    found = datasets(site, keys)
    assert {"jpg", "wav", "hls", "testing/uploads", "testing/parsers"} <= set(found)
    entries = manifest_entries()
    for key, block in found.items():
        for download in block["distribution"]:
            entry = entries[download["contentUrl"].removeprefix("https://loremfile.dev/")]
            assert download["contentSize"] == f"{entry['bytes']} bytes", (key, entry["path"])
            assert download["sha256"] == entry["sha256"], (key, entry["path"])


def test_every_dataset_is_dated_like_its_sitemap_entry(site: Path, keys: dict[str, Path]) -> None:
    lastmods = set(re.findall(r"<lastmod>([^<]+)</lastmod>", text(site, "sitemap.xml")))
    assert lastmods == {WHEN.date().isoformat()}
    found = datasets(site, keys)
    assert len(found) > 80 and "pdf" in found
    assert {block["dateModified"] for block in found.values()} == lastmods


def test_the_formats_page_is_a_collection_of_every_format_page(site: Path) -> None:
    blocks = checks._jsonld(text(site, "formats"))
    collection = next(b for b in blocks if b.get("@type") == "CollectionPage")
    items = collection["mainEntity"]["itemListElement"]
    formats = sorted({path.split("/", 1)[0] for path in fixtures()})
    assert {"jpg", "wav", "7z"} <= set(formats)
    assert [item["url"] for item in items] == [f"https://loremfile.dev/{f}" for f in formats]
    assert [item["position"] for item in items] == list(range(1, len(formats) + 1))
    assert collection["mainEntity"]["numberOfItems"] == len(formats)


def test_the_changelog_is_a_tech_article(site: Path) -> None:
    types = [b["@type"] for b in checks._jsonld(text(site, "changelog"))]
    assert types == ["TechArticle", "BreadcrumbList"]


#: ADR-028: no person or organization in public markup.
PARTY = re.compile(r'"(creator|publisher|author)"|"Organization"')


def parties(html_text: str) -> list[str]:
    return [m.group(0) for b in checks._jsonld(html_text) for m in PARTY.finditer(json.dumps(b))]


def test_no_structured_data_names_a_creator_or_publisher(site: Path, keys: dict[str, Path]) -> None:
    pages = [key for key in keys if routes.is_page(key)]
    assert {"jpg", "formats", "changelog"} <= set(pages)
    assert {key: parties(text(site, key)) for key in pages if parties(text(site, key))} == {}


def test_the_party_check_finds_a_publisher() -> None:
    block = {"@type": "Dataset", "publisher": {"@type": "Organization", "name": "x"}}
    page = f'<script type="application/ld+json">{json.dumps(block)}</script>'
    assert parties(page) == ['"publisher"', '"Organization"']


# --- Markdown twins (docs/04 §5b) ----------------------------------------------------------


TWIN_ROW = re.compile(r"^\| \[`([^`]+)`\]\(https://loremfile\.dev/\1\) \|", re.M)


def test_every_format_page_has_a_twin_listing_exactly_its_files(site: Path) -> None:
    current = {
        e["path"]
        for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]
        if e.get("status", "active") == "active" and not e.get("supersededBy")
    }
    formats = sorted({path.split("/", 1)[0] for path in fixtures()})
    assert {"jpg", "wav", "7z"} <= set(formats)
    for fmt in formats:
        body = text(site, routes.twin_key(fmt))
        table = body.split("\n## Files\n", 1)[1].split("\n## ", 1)[0]
        listed = set(TWIN_ROW.findall(table))
        assert listed == {p for p in current if p.startswith(f"{fmt}/")}, fmt
        assert f"The page: <https://loremfile.dev/{fmt}>." in body
        assert f"<https://loremfile.dev/{fmt}/index.json>" in body
        assert "<!-- file:" not in body


def test_a_guide_twin_lists_the_files_its_prose_names_in_order(site: Path) -> None:
    for slug in ("uploads", "parsers", "media-playback"):
        source = (ROOT / "site" / "content" / "testing" / f"{slug}.md").read_text()
        named = re.findall(r"^<!-- file: (\S+) -->$", source, re.M)
        assert len(named) > 5, slug
        body = text(site, routes.twin_key(f"testing/{slug}"))
        assert TWIN_ROW.findall(body) == named, slug


def test_a_twin_row_states_the_manifest_measurements(site: Path) -> None:
    entry = manifest_entries()["jpg/cmyk-640x640.jpg"]
    row = build.twin_row(entry)
    assert row in text(site, routes.twin_key("jpg"))
    assert f"{entry['bytes']:,} bytes" in row and entry["mime"] in row
    props = entry["props"]
    assert f"{props['width']}x{props['height']}, {props['mode']}" in row


def test_a_twin_names_a_superseded_file_and_its_replacement(site: Path) -> None:
    body = text(site, routes.twin_key("jpg"))
    assert "- `jpg/cmyk-640x480.jpg` is replaced by `jpg/cmyk-640x640.jpg`." in body
    assert "jpg/cmyk-640x480.jpg" not in body.split("\n## Files\n", 1)[1].split("\n## ", 1)[0]


def test_twins_are_markdown_and_stay_out_of_every_index(site: Path, keys: dict[str, Path]) -> None:
    twins = [key for key in keys if key.startswith("_formats/") and key.endswith(".md")]
    assert {"_formats/jpg.md", "_formats/testing/uploads.md"} <= set(twins)
    assert len(twins) == len({p.split("/", 1)[0] for p in fixtures()}) + 3
    for key in twins:
        assert routes.content_type(key) == "text/markdown; charset=utf-8"
    for index in ("sitemap.xml", "search-index.json", "llms.txt", "llms-full.txt"):
        assert "index.md" not in text(site, index), index


def advertises_twin(html_text: str) -> bool:
    return bool(re.search(r'<link rel="alternate" type="text/markdown"', html_text))


def test_the_advertising_check_finds_a_markdown_alternate() -> None:
    link = '<link rel="alternate" type="text/markdown" href="https://loremfile.dev/pdf/index.md">'
    assert advertises_twin(f"<head>{link}</head>")
    assert not advertises_twin('<link rel="alternate" type="application/json" href="x">')


def test_no_page_advertises_a_twin_before_production_serves_it(
    site: Path, keys: dict[str, Path]
) -> None:
    """Owner, 2026-10-11: no `rel="alternate" type="text/markdown"` and no llms.txt line until
    the twin URLs resolve in production. The PR that adds them removes this test."""
    pages = [key for key in keys if routes.is_page(key)]
    assert {"jpg", "testing/uploads"} <= set(pages)
    assert [key for key in pages if advertises_twin(text(site, key))] == []
    link = re.compile(r'<link rel="alternate" type="([^"]+)" href="([^"]+)">')
    alternate = link.findall(text(site, "jpg"))
    assert alternate == [("application/json", "https://loremfile.dev/jpg/index.json")]


def test_a_twin_marker_the_page_may_not_list_stops_the_build() -> None:
    page = build.Page("x", "X", "A page.", "doc.html")
    with pytest.raises(build.SiteError, match=re.escape("bin/never-published.bin")):
        build.twin(page, "<!-- file: bin/never-published.bin -->\n", "x.md", {})


def test_consecutive_markers_share_one_table() -> None:
    entries = manifest_entries()
    page = build.Page("x", "X", "A page.", "doc.html")
    text_ = "<!-- file: bin/10mb.bin -->\n\n<!-- file: bin/10mb-plus-1.bin -->\n\nProse.\n"
    body = build.twin(page, text_, "x.md", entries)
    assert body.count("| Path | Size | MIME | Properties |") == 1
    assert TWIN_ROW.findall(body) == ["bin/10mb.bin", "bin/10mb-plus-1.bin"]


#: Built keys a deploy deliberately does not purge, because their bytes never change: the
#: IndexNow key file is a constant, and a schema version is published once (docs/04 §2).
NEVER_PURGED = {routes.INDEXNOW_KEY_FILE, "schema/manifest-v1.json"}


def unpurged(keys: dict[str, Path]) -> list[str]:
    """Built keys whose public URL no purge target reaches, by URL or by prefix."""
    prefixes, files = purge.site_targets(sorted({p.split("/", 1)[0] for p in fixtures()}))
    reached = set(files)
    return sorted(
        key
        for key in keys
        if f"https://loremfile.dev{routes.public_path(key)}" not in reached
        and not any(f"loremfile.dev{routes.public_path(key)}".startswith(p) for p in prefixes)
    )


def test_every_built_key_that_can_change_is_purged_on_deploy(keys: dict[str, Path]) -> None:
    """A page the purge misses is served stale for up to five minutes after a deploy, and
    the deploy's own verify-live then reads it as a hash mismatch. `/testing` was missed
    from 2026-10-11 (#69) until this check existed."""
    assert {"testing/uploads", "_formats/jpg.md", "jpg", "llms.txt"} <= set(keys)
    assert set(unpurged(keys)) == NEVER_PURGED
