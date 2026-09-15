"""`loremfile site build`: the static site, rendered at one commit (docs/07 §4).

Deterministic for a commit: the only date read is the committer date, so the daily health
check rebuilds the deployed site and compares every key with production (docs/09 §3.3).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from loremfile import config
from loremfile.catalog import Catalog, FormatCatalog
from loremfile.manifest import Manifest
from loremfile.site import icons, markdown, routes

#: docs/05 §8, in order.
POPULAR = (
    "pdf/a4-3pages.pdf",
    "png/640x480.png",
    "jpg/1920x1080.jpg",
    "mp4/720p-5s.mp4",
    "mp3/sine-440hz-30s.mp3",
    "csv/people-1000.csv",
    "json/people-1000.json",
    "docx/1page.docx",
    "xlsx/1sheet-1000rows.xlsx",
    "bin/10mib-plus-1.bin",
)
#: docs/05 §5, in order.
FAMILIES = (
    ("documents", "Documents"),
    ("images", "Images"),
    ("video", "Video"),
    ("audio", "Audio"),
    ("text", "Text"),
    ("web", "Web"),
    ("data", "Data"),
    ("archives", "Archives"),
    ("fonts", "Fonts"),
    ("binary", "Binary"),
    ("calendar-mail", "Calendar and mail"),
    ("certificates", "Certificates"),
    ("edge", "Edge cases"),
)
LABELS = {
    "arrow": "Arrow",
    "avro": "Avro",
    "bin": "binary",
    "geojson": "GeoJSON",
    "jpg": "JPEG",
    "log": "log",
    "md": "Markdown",
    "parquet": "Parquet",
    "sqlite": "SQLite",
    "txt": "text",
}
#: Top-level keys the site owns; a format of the same name would overwrite one.
RESERVED = frozenset({"formats", "docs", "legal", "changelog", "status", "assets", "schema"})
SECURITY_TXT_DAYS = 365
#: docs/04 §6, exactly; tests/unit/test_site_build.py compares the two.
ROBOTS_TXT = """User-agent: *
Allow: /

User-agent: GPTBot
User-agent: OAI-SearchBot
User-agent: ChatGPT-User
User-agent: OAI-AdsBot
User-agent: ClaudeBot
User-agent: Claude-User
User-agent: Claude-SearchBot
User-agent: Google-Extended
Disallow: /legal/imprint
Disallow: /legal/privacy

Sitemap: https://loremfile.dev/sitemap.xml
"""
HEADING = re.compile(r"#{1,6} ")
#: (key, title, description, kind, source). `section` sources name a heading prefix.
DOCS = (
    (
        "docs/getting-started",
        "Getting started",
        "How the URLs work, how to fetch a fixture, and how to verify what you downloaded.",
        "content",
        "pages/getting-started.md",
    ),
    (
        "docs/naming",
        "Naming and sizes",
        "The fixture naming grammar, and why kb and kib are different sizes.",
        "content",
        "pages/naming.md",
    ),
    (
        "docs/http-contract",
        "HTTP contract",
        "Every header, status code and caching rule loremfile.dev promises.",
        "repository",
        "docs/03-http-contract.md",
    ),
    (
        "docs/manifest",
        "Manifest and discovery files",
        "manifest.json, sha256sums.txt, per-format indexes, llms.txt, robots.txt and security.txt.",
        "repository",
        "docs/04-manifest-and-discovery.md",
    ),
    (
        "docs/faq",
        "FAQ",
        "Hotlinking, rate limits, why files are not indexed, mirroring and accessibility.",
        "content",
        "pages/faq.md",
    ),
    (
        "docs/contributing",
        "Contributing",
        "How to request a fixture, and what a new one needs before it is published.",
        "repository",
        "CONTRIBUTING.md",
    ),
    (
        "docs/security-policy",
        "Security policy",
        "How to report a vulnerability in loremfile.dev, and what is in scope.",
        "section",
        "## 7. Disclosure policy",
    ),
)
#: (key, heading in docs/13, description). The quoted text is published verbatim.
LEGAL = (
    ("legal/license", "### 1.1 Licence page", "Licences for the files, the code and this website."),
    ("legal/terms", "## 2. Terms of use", "The terms of use of loremfile.dev."),
    (
        "legal/privacy",
        "## 3. Privacy notice",
        "What loremfile.dev processes, who is responsible, and your rights.",
    ),
    ("legal/imprint", "## 3b. Impressum", "Impressum of loremfile.dev (§ 18 Abs. 1 MStV)."),
)


class SiteError(ValueError):
    """The site cannot be built from what the repository holds."""


@dataclass
class Page:
    key: str
    h1: str
    description: str
    template: str
    title: str = ""
    crumbs: list[tuple[str, str]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    jsonld: list[dict[str, Any]] = field(default_factory=list)
    robots: str | None = None

    @property
    def canonical(self) -> str:
        return routes.absolute_url(self.key)

    @property
    def listed(self) -> bool:
        """In the sitemap and the structured data; ADR-028 keeps the operator's pages out."""
        return self.robots is None


@dataclass
class BuildReport:
    keys: int = 0
    pages: int = 0
    bytes: int = 0

    def render(self) -> str:
        return f"  {self.keys} keys, {self.pages} pages, {self.bytes:,} bytes"


def committed_at(root: Path) -> dt.datetime:
    """The committer date of HEAD: the build's only clock (docs/07 §4)."""
    executable = shutil.which("git")
    if executable is None:
        raise SiteError("git is not on PATH")
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [executable, "log", "-1", "--format=%cI", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0 or not done.stdout.strip():
        raise SiteError(f"git log failed: {done.stderr.strip()}")
    return dt.datetime.fromisoformat(done.stdout.strip()).astimezone(dt.UTC)


def trusted(html: str) -> Markup:
    """HTML this module produced: markdown-it output with raw HTML disabled, the committed
    mark, and JSON with `</` escaped. Nothing a visitor or a secret supplies reaches here."""
    return Markup(html)  # noqa: S704 - see the docstring


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def label(fmt: str) -> str:
    return LABELS.get(fmt, fmt.upper())


def human_bytes(count: int) -> str:
    for unit, size in (("GB", 10**9), ("MB", 10**6), ("KB", 10**3)):
        if count >= size:
            return f"{f'{count / size:.1f}'.removesuffix('.0')} {unit}"
    return f"{count} B"


def key_props(props: dict[str, Any]) -> str:
    """At most four measured properties worth reading in a table cell."""
    shown: list[str] = []
    if "width" in props and "height" in props:
        shown.append(f"{props['width']}x{props['height']}")
    for name in ("pages", "slides", "sheets", "chapters", "segments", "features"):
        if name in props:
            shown.append(f"{props[name]} {name}")
    if "rows" in props:
        shown.append(f"{props['rows']:,} rows")
    if "duration_ms" in props:
        shown.append(f"{props['duration_ms'] / 1000:g} s")
    shown += [str(props[name]) for name in ("vcodec", "acodec") if props.get(name)]
    if "encoding" in props and "rows" not in props:
        shown.append(str(props["encoding"]) + (" with BOM" if props.get("bom") else ""))
        if props.get("line_ending"):
            shown.append(str(props["line_ending"]).upper())
    if props.get("animated"):
        shown.append(f"{props.get('frames')} frames")
    if props.get("encrypted") is True:
        shown.append("encrypted")
    return ", ".join(shown[:4])


def embed_snippet(family: str, url: str) -> str:
    if family == "images":
        return f'<img src="{url}" alt="">'
    if family == "video":
        return f'<video src="{url}" controls></video>'
    if family == "audio":
        return f'<audio src="{url}" controls></audio>'
    return f'<a href="{url}">download</a>'


def section(path: Path, heading: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.startswith(heading):
            body: list[str] = []
            for following in lines[index + 1 :]:
                if HEADING.match(following):
                    break
                body.append(following)
            return "\n".join(body).strip("\n") + "\n"
    raise SiteError(f"{path.name} has no section starting {heading!r}")


def quoted(text: str) -> tuple[str, str]:
    """A legal section's blockquote, published verbatim: (its bold title, its Markdown)."""
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith(">"):
            lines.append(line[1:].removeprefix(" "))
        elif lines and line.strip():
            break
    title = re.fullmatch(r"\*\*(.+)\*\*", lines[0].strip()) if lines else None
    if title is None:
        raise SiteError("a legal section's quote must open with a bold title")
    body: list[str] = []
    for line in lines[1:]:
        if line.startswith("**") and body and body[-1].strip():
            body.append("")
        body.append(line)
    text = re.sub(r"`(%%IMPRINT_[A-Z_]+%%)`", r"\1", "\n".join(body))
    return title.group(1), text.strip("\n") + "\n"


def content(root: Path, relative: str) -> str:
    path = root / "site" / "content" / relative
    if not path.is_file():
        raise SiteError(f"site/content/{relative} is missing (docs/07 §5)")
    return path.read_text(encoding="utf-8")


def inline_svg(mark: bytes) -> str:
    """The mark as inline markup: no XML declaration, no namespace URL, hidden from readers."""
    text = re.sub(r"<\?xml[^>]*\?>\s*", "", mark.decode("utf-8"))
    text = text.replace(' xmlns="http://www.w3.org/2000/svg"', "")
    return text.replace(
        "<svg ", '<svg aria-hidden="true" focusable="false" class="mark" ', 1
    ).strip()


def breadcrumbs(crumbs: list[tuple[str, str]], name: str, url: str) -> dict[str, Any]:
    items = [(label_, f"{config.BASE_URL}{href[1:]}") for label_, href in crumbs] + [(name, url)]
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": position, "name": text, "item": item}
            for position, (text, item) in enumerate(items, start=1)
        ],
    }


def article(page: Page) -> list[dict[str, Any]]:
    return [
        {
            "@context": "https://schema.org",
            "@type": "TechArticle",
            "headline": page.h1,
            "description": page.description,
            "url": page.canonical,
        },
        breadcrumbs(page.crumbs, page.h1, page.canonical),
    ]


# --- pages ------------------------------------------------------------------------------------


def format_pages(root: Path, manifest: Manifest, catalogs: dict[str, FormatCatalog]) -> list[Page]:
    formats = sorted({entry["format"] for entry in manifest.entries})
    pages: list[Page] = []
    for fmt in formats:
        if fmt in RESERVED or fmt not in catalogs:
            raise SiteError(f"format {fmt!r} is reserved by the site or absent from the catalog")
        info = catalogs[fmt]
        entries = sorted(
            (e for e in manifest.entries if e["format"] == fmt), key=lambda e: e["path"]
        )
        active = [e for e in entries if e.get("status", "active") == "active"]
        rows = [
            {
                "path": e["path"],
                "name": e["path"].split("/", 1)[1],
                "url": f"{config.BASE_URL}{e['path']}",
                "size": human_bytes(e["bytes"]),
                "exact": f"{e['bytes']:,} bytes",
                "props": key_props(e.get("props") or {}),
                "description": e["description"],
                "curl": f"curl -O {config.BASE_URL}{e['path']}",
                "embed": embed_snippet(info.family.value, f"{config.BASE_URL}{e['path']}"),
            }
            for e in active
        ]
        plural = "" if len(active) == 1 else "s"
        page = Page(
            key=fmt,
            h1=info.seo_title,
            title=f"{info.seo_title} · loremfile.dev",
            description=(
                f"{len(active)} sample {label(fmt)} file{plural} with stable URLs you can "
                "hotlink. No signup, no keys, CC0."
            ),
            template="format.html",
            crumbs=[("Home", "/"), ("Formats", "/formats")],
            context={
                "label": label(fmt),
                "intro": trusted(markdown.render(content(root, f"formats/{fmt}.md"))),
                "rows": rows,
                "removed": [e for e in entries if e.get("status") == "removed"],
                "related": [
                    {"format": other, "label": label(other)}
                    for other in info.related
                    if other in formats
                ],
                "index_url": routes.absolute_url(routes.format_index_key(fmt)),
            },
        )
        page.jsonld = [
            {
                "@context": "https://schema.org",
                "@type": "Dataset",
                "name": info.seo_title,
                "description": " ".join(info.description.split()),
                "url": page.canonical,
                "license": config.LICENSE_URL,
                "isAccessibleForFree": True,
                "distribution": [
                    {"@type": "DataDownload", "contentUrl": row["url"], "encodingFormat": e["mime"]}
                    for row, e in zip(rows, active, strict=True)
                ],
            },
            breadcrumbs(page.crumbs, label(fmt), page.canonical),
        ]
        pages.append(page)
    return pages


def families(manifest: Manifest, catalogs: dict[str, FormatCatalog]) -> list[dict[str, Any]]:
    counts = Counter(entry["format"] for entry in manifest.active)
    formats = sorted({entry["format"] for entry in manifest.entries})
    grouped = []
    for family, name in FAMILIES:
        members = [
            {"format": fmt, "label": label(fmt), "count": counts.get(fmt, 0)}
            for fmt in formats
            if catalogs[fmt].family.value == family
        ]
        if members:
            grouped.append({"label": name, "formats": members})
    return grouped


def home_page(root: Path, manifest: Manifest, catalogs: dict[str, FormatCatalog]) -> Page:
    by_path = {entry["path"]: entry for entry in manifest.active}
    missing = [path for path in POPULAR if path not in by_path]
    if missing:
        raise SiteError(f"popular paths not in the manifest: {', '.join(missing)} (docs/05 §8)")
    return Page(
        key="index.html",
        h1="Sample files you can hotlink",
        title="loremfile.dev — sample files you can hotlink",
        description=(
            "Free, CC0 sample files and test fixtures with stable URLs you can hotlink: PDFs, "
            "images, audio, video, office documents and data files. No signup."
        ),
        template="home.html",
        context={
            "pitch": trusted(markdown.render(content(root, "home.md"))),
            "families": families(manifest, catalogs),
            "popular": [
                {
                    "path": path,
                    "url": f"{config.BASE_URL}{path}",
                    "size": human_bytes(by_path[path]["bytes"]),
                    "description": by_path[path]["description"],
                }
                for path in POPULAR
            ],
            "count": len(manifest.active),
        },
        jsonld=[
            {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": config.SITE_HOST,
                "url": config.BASE_URL,
                "description": "Free, CC0 sample files and test fixtures you can hotlink.",
            },
            {
                "@context": "https://schema.org",
                "@type": "SoftwareSourceCode",
                "name": "loremfile",
                "codeRepository": config.SOURCE_URL,
                "license": f"{config.SOURCE_URL}/blob/main/LICENSE",
                "programmingLanguage": "Python",
            },
        ],
    )


def formats_page(manifest: Manifest, catalogs: dict[str, FormatCatalog]) -> Page:
    active = manifest.active
    rows = []
    for fmt in sorted({entry["format"] for entry in manifest.entries}):
        mine = [e for e in active if e["format"] == fmt]
        rows.append(
            {
                "format": fmt,
                "label": label(fmt),
                "family": dict(FAMILIES)[catalogs[fmt].family.value],
                "count": len(mine),
                "size": human_bytes(sum(e["bytes"] for e in mine)),
                "mime": catalogs[fmt].mime,
            }
        )
    return Page(
        key="formats",
        h1="All formats",
        description=f"Every format on loremfile.dev: {len(rows)} formats, {len(active)} files.",
        template="formats.html",
        crumbs=[("Home", "/")],
        context={"rows": rows},
    )


def doc_pages(root: Path) -> list[Page]:
    pages: list[Page] = []
    crumbs = [("Home", "/"), ("Docs", "/docs")]
    for key, title, description, kind, source in DOCS:
        if kind == "content":
            text = content(root, source)
            if key == "docs/faq":
                statement = section(root / "docs" / "13-legal-and-policy.md", "## 9. Accessibility")
                text = f"{text.rstrip()}\n\n## Accessibility\n\n{statement}"
            body = markdown.render(text)
        elif kind == "repository":
            body = markdown.render(
                markdown.strip_title((root / source).read_text("utf-8"))[1], source=source
            )
        else:
            body = markdown.render(section(root / "docs" / "10-security.md", source))
        page = Page(
            key, title, description, "doc.html", crumbs=crumbs, context={"body": trusted(body)}
        )
        page.jsonld = article(page)
        pages.append(page)
    index = Page(
        "docs",
        "Documentation",
        "Guides, the HTTP contract and the manifest format for loremfile.dev.",
        "doc.html",
        crumbs=[("Home", "/")],
        context={"body": trusted(""), "items": [(f"/{p.key}", p.h1, p.description) for p in pages]},
    )
    index.jsonld = article(index)
    return [index, *pages]


def legal_pages(root: Path) -> list[Page]:
    source = root / "docs" / "13-legal-and-policy.md"
    crumbs = [("Home", "/"), ("Legal", "/legal")]
    pages: list[Page] = []
    for key, heading, description in LEGAL:
        title, text = quoted(section(source, heading))
        page = Page(
            key,
            title,
            description,
            "legal.html",
            crumbs=crumbs,
            context={"body": trusted(markdown.render(text, breaks=key == "legal/imprint"))},
            robots=routes.LEGAL_ROBOTS if key in routes.LEGAL_KEYS else None,
        )
        page.jsonld = article(page) if page.listed else []
        pages.append(page)
    index = Page(
        "legal",
        "Legal",
        "Licences, terms of use, privacy notice and Impressum of loremfile.dev.",
        "legal.html",
        crumbs=[("Home", "/")],
        context={"body": trusted(""), "items": [(f"/{p.key}", p.h1, p.description) for p in pages]},
    )
    index.jsonld = article(index)
    return [index, *pages]


def changelog_page(root: Path) -> Page:
    text = markdown.strip_title((root / "CHANGELOG.md").read_text(encoding="utf-8"))[1]
    return Page(
        "changelog",
        "Changelog",
        "Every catalog version of loremfile.dev and what it added.",
        "changelog.html",
        crumbs=[("Home", "/")],
        context={"body": trusted(markdown.render(text, source="CHANGELOG.md"))},
    )


def status_page() -> Page:
    return Page(
        "status",
        "Status",
        "How loremfile.dev checks itself every day, and where to see a failing check.",
        "status.html",
        crumbs=[("Home", "/")],
        context={"issues": f"{config.SOURCE_URL}/issues?q=is%3Aissue+is%3Aopen+label%3Ahealth"},
    )


# --- discovery files ----------------------------------------------------------------------------


def format_index(manifest: Manifest, fmt: str) -> bytes:
    """docs/04 §4: the manifest's shape, one format's active fixtures, no `formats` array."""
    document = manifest.to_document()
    active = [
        e
        for e in document["fixtures"]
        if e["format"] == fmt and e.get("status", "active") == "active"
    ]
    document.pop("formats")
    document.update(count=len(active), total_bytes=sum(e["bytes"] for e in active), fixtures=active)
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()


def search_index(manifest: Manifest) -> bytes:
    rows = [
        {"path": e["path"], "bytes": e["bytes"], "description": e["description"]}
        for e in sorted(manifest.active, key=lambda e: e["path"])
    ]
    return (json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def llms(manifest: Manifest, catalogs: dict[str, FormatCatalog], *, full: bool) -> bytes:
    """docs/04 §5. Lists fixtures and formats only, never a legal page (ADR-028)."""
    base = config.BASE_URL
    lines = [
        "# loremfile.dev",
        "",
        "> Free, CC0, hotlink-friendly sample files and test fixtures for every common file "
        "type. Stable URLs, open CORS, byte-range support, SHA-256 manifest. No ads, no signup, "
        "no rate-limit keys.",
        "",
        "## How to use",
        f"- Every fixture: {base}{{format}}/{{name}} — see the manifest for all paths.",
        f"- Machine-readable list of everything: {base}manifest.json (JSON, includes sha256, "
        "bytes, mime, measured properties)",
        f"- Per-format lists: {base}{{format}}/index.json",
        f"- Verify: {base}sha256sums.txt",
        "",
        "## Formats",
    ]
    for group in families(manifest, catalogs):
        links = ", ".join(
            f"[{item['format']}]({base}{item['format']}) ({item['count']})"
            for item in group["formats"]
        )
        lines.append(f"- {group['label']}: {links}")
    lines += [
        "",
        "## Rules",
        "- Query strings are ignored. Stay under 30 requests/second per IP.",
        f"- License: CC0 1.0 for all fixtures. Source: {config.SOURCE_URL}",
    ]
    if full:
        lines += ["", "## Fixtures"]
        active = sorted(manifest.active, key=lambda e: e["path"])
        for fmt in sorted({e["format"] for e in active}):
            lines += ["", f"### {fmt}", "", "| Path | Bytes | Description | Properties |"]
            lines.append("|---|---|---|---|")
            for e in (e for e in active if e["format"] == fmt):
                cells = (e["description"], key_props(e.get("props") or {}))
                description, props = (cell.replace("|", "\\|") for cell in cells)
                lines.append(f"| {e['path']} | {e['bytes']} | {description} | {props} |")
    return ("\n".join(lines) + "\n").encode()


def sitemap(pages: list[Page], committed: dt.datetime) -> bytes:
    lastmod = committed.date().isoformat()
    urls = sorted(page.canonical for page in pages if page.listed)
    body = "".join(
        f"  <url><loc>{xml_escape(url)}</loc><lastmod>{lastmod}</lastmod></url>\n" for url in urls
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}</urlset>\n"
    ).encode()


def security_txt(committed: dt.datetime) -> bytes:
    expires = committed.astimezone(dt.UTC) + dt.timedelta(days=SECURITY_TXT_DAYS)
    lines = [
        f"Contact: {config.SOURCE_URL}/security/advisories/new",
        "Contact: mailto:security@loremfile.dev",
        f"Expires: {expires:%Y-%m-%dT%H:%M:%SZ}",
        "Preferred-Languages: en",
        f"Canonical: {config.BASE_URL}.well-known/security.txt",
        f"Policy: {config.BASE_URL}docs/security-policy",
    ]
    return ("\n".join(lines) + "\n").encode()


# --- the build -------------------------------------------------------------------------------


def render_page(env: Environment, page: Page, site: dict[str, Any]) -> bytes:
    jsonld = [
        trusted(json.dumps(item, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
        for item in page.jsonld
    ]
    title = page.title or f"{page.h1} · loremfile.dev"
    html = env.get_template(page.template).render(
        page=page, title=title, site=site, jsonld=jsonld, **page.context
    )
    return html.encode("utf-8")


def build(out: Path, *, root: Path, committed: dt.datetime) -> BuildReport:
    manifest = Manifest.load(root / "manifest.json")
    catalogs = {c.format: c for c in Catalog.load(root / "catalog").formats}
    env = Environment(
        loader=FileSystemLoader(root / "site" / "templates"),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    static = root / "site" / "static"
    css, js, mark = ((static / name).read_bytes() for name in ("site.css", "site.js", "mark.svg"))
    css_key, js_key = f"assets/site.{sha256(css)[:12]}.css", f"assets/site.{sha256(js)[:12]}.js"
    files: dict[str, bytes] = {
        css_key: css,
        js_key: js,
        "assets/mark.svg": mark,
        "assets/og.png": icons.og_card(),
        "favicon.ico": icons.favicon_ico(),
        "apple-touch-icon.png": icons.mark_png(180),
    }
    site = {
        "css": f"/{css_key}",
        "js": f"/{js_key}",
        "mark": trusted(inline_svg(mark)),
        "og_image": routes.absolute_url("assets/og.png"),
        "source": config.SOURCE_URL,
    }
    pages = [
        home_page(root, manifest, catalogs),
        *format_pages(root, manifest, catalogs),
        formats_page(manifest, catalogs),
        *doc_pages(root),
        *legal_pages(root),
        changelog_page(root),
        status_page(),
    ]
    for page in pages:
        if page.key.endswith(".html") and page.key != "index.html":
            raise SiteError(
                f"{page.key}: only the root page key may end in .html (routes.disk_path)"
            )
        if page.key in files:
            raise SiteError(f"two outputs claim the key {page.key!r}")
        files[page.key] = render_page(env, page, site)
    formats = sorted({entry["format"] for entry in manifest.entries})
    files.update({routes.format_index_key(fmt): format_index(manifest, fmt) for fmt in formats})
    files.update(
        {
            "manifest.json": (root / "manifest.json").read_bytes(),
            "formats.json": (root / "formats.json").read_bytes(),
            "sha256sums.txt": (root / "sha256sums.txt").read_bytes(),
            "schema/manifest-v1.json": (
                root / "src/loremfile/schema/manifest-v1.json"
            ).read_bytes(),
            "search-index.json": search_index(manifest),
            "llms.txt": llms(manifest, catalogs, full=False),
            "llms-full.txt": llms(manifest, catalogs, full=True),
            "sitemap.xml": sitemap(pages, committed),
            "robots.txt": ROBOTS_TXT.encode(),
            ".well-known/security.txt": security_txt(committed),
        }
    )
    if out.exists():
        shutil.rmtree(out)
    for key, data in sorted(files.items()):
        path = out / routes.disk_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    not_found = Page("404", "Not found", "No page or fixture lives at this address.", "404.html")
    (out.parent / "site-404.html").write_bytes(render_page(env, not_found, site))
    return BuildReport(keys=len(files), pages=len(pages), bytes=sum(map(len, files.values())))
