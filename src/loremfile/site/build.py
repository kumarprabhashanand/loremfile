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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from loremfile import config
from loremfile.catalog import Catalog, FormatCatalog
from loremfile.manifest import Manifest
from loremfile.site import icons, markdown, page_dates, routes

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
RESERVED = frozenset(
    {"formats", "docs", "legal", "changelog", "status", "assets", "schema", "testing"}
)
SECURITY_TXT_DAYS = 365
#: docs/04 §6, exactly; tests/unit/test_site_build.py compares the two.
ROBOTS_TXT = """User-agent: *
Content-Signal: search=yes, ai-input=yes, ai-train=yes
Allow: /

User-agent: GPTBot
User-agent: OAI-SearchBot
User-agent: ChatGPT-User
User-agent: OAI-AdsBot
User-agent: ClaudeBot
User-agent: Claude-User
User-agent: Claude-SearchBot
User-agent: CCBot
User-agent: PerplexityBot
User-agent: Perplexity-User
User-agent: Bytespider
User-agent: meta-externalagent
User-agent: meta-externalfetcher
User-agent: Amazonbot
User-agent: Diffbot
User-agent: MistralAI-User
User-agent: DuckAssistBot
User-agent: AgentDataBot
User-agent: BixelBot
User-agent: CloudflareBrowserRenderingCrawler
User-agent: Kimi-Agent
User-agent: qodercli
User-agent: KeenableBot
User-agent: Keenable-User
User-agent: GrokBot
User-agent: GrokAppAndroid
User-agent: Hunyuan
User-agent: MoonshotBot
User-agent: xAI-Grok
User-agent: YiBot
User-agent: KimiBot
User-agent: Kimi-SearchBot
User-agent: Kimi-User
User-agent: CledaraBot
User-agent: Codex
User-agent: ElevenlabsBot
User-agent: ExaUser
User-agent: HarkBot
User-agent: Instinct
User-agent: Muse
User-agent: Google-Extended
User-agent: Applebot-Extended
Content-Signal: search=yes, ai-input=yes, ai-train=yes
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
        "docs/languages",
        "Use it from your language",
        "Fetching a fixture and verifying its hash, in shell, Python, JavaScript, Go and Java.",
        "content",
        "pages/languages.md",
    ),
    (
        "docs/mcp",
        "MCP server",
        "Connect an agent to loremfile.dev: the npx and uvx configs, and the three read-only "
        "tools.",
        "content",
        "pages/mcp.md",
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


#: (key, title, description, source): pages chosen by the job a file tests, not its format.
TESTING = (
    (
        "testing/uploads",
        "Sample files for testing file uploads",
        "Files on the edge of every upload check: exact size limits, mislabelled types, "
        "rotated and CMYK images, hostile and encrypted archives. Free, CC0, hotlinkable.",
        "testing/uploads.md",
    ),
    (
        "testing/parsers",
        "Sample files for testing parsers and error handling",
        "Files that must load correctly, must fail, may be recovered or split readers, each "
        "with its known contents or measured outcome. Free, CC0, hotlinkable.",
        "testing/parsers.md",
    ),
    (
        "testing/media-playback",
        "Sample files for testing media playback and seeking",
        "Video and audio that test playback and seeking: where the index sits, range "
        "requests, codecs, missing tracks and adaptive HLS. Free, CC0, hotlinkable.",
        "testing/media-playback.md",
    ),
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
    #: (media type, absolute URL) pairs for `<link rel="alternate">` in the head.
    alternates: list[tuple[str, str]] = field(default_factory=list)
    #: The page as Markdown, published at `/{key}/index.md` (docs/04 §5b), or None.
    twin: str | None = None

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
    #: Every sitemap page's date as this build gave it, and the keys that differ from the
    #: committed record (docs/04 §7): empty when `page-dates.json` is current.
    dates: page_dates.Record = field(default_factory=dict)
    stale: list[str] = field(default_factory=list)

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


#: What a results page shows of a title and a description before cutting them off.
TITLE_LIMIT = 60
DESCRIPTION_LIMIT = 155
#: The twelve formats with search demand (2026-10-22). Their labelled titles keep both words
#: people type, "Sample" and "test"; ogg, tiff and arrow keep 1.9.0's head.
DEMAND_FORMATS = frozenset(
    {"mp3", "mp4", "parquet", "docx", "pptx", "mkv", "png", "jpg", "pdf", "csv", "zip", "wav"}
)
#: Where the query differs from "sample {format} files for testing": "mp3 test file", and
#: "jpg", which people type where the format's name (and its label) is JPEG.
QUERY_HEADS = {"mp3": "Sample {name} test file{s}", "jpg": "Sample JPG file{s} for testing"}


def title_head(fmt: str) -> str:
    """The head of a format's labelled title (docs/05 §1 rule 9)."""
    if fmt in QUERY_HEADS:
        return QUERY_HEADS[fmt]
    if fmt in DEMAND_FORMATS:
        return "Sample {name} file{s} for testing"
    return "Sample {name} file{s}"


def labelled_title(name: str, labels: list[str], head: str = "Sample {name} file{s}") -> str:
    """`{head}: {labels}`, cut at the last whole label that fits.

    No brand suffix and no adjectives: the title leads with what the page holds, in the
    order the catalog lists it (docs/05 §1 rule 9). The head is never cut: a word people
    type is worth more than a label, so a first label too long to follow it stops the build
    until it is shortened.
    """
    head = f"{head.format(name=name, s='' if len(labels) == 1 else 's')}: "
    if not labels or len(head + labels[0]) > TITLE_LIMIT:
        raise SiteError(f"{head!r}: shorten the first label to fit within {TITLE_LIMIT}")
    shown: list[str] = []
    for text in labels:
        if len(head + ", ".join([*shown, text])) > TITLE_LIMIT:
            break
        shown.append(text)
    return head + ", ".join(shown)


def page_labels(info: FormatCatalog, served: list[dict[str, Any]]) -> list[str]:
    """One label per recommended file, in catalog order; empty unless every one has a label.

    A superseded file never contributes one: titles and descriptions advertise what to use,
    and the page names the replacement below the table. Skipped by its entry, not by where
    the catalog happens to list it.
    """
    recommended = {e["path"] for e in served if not e.get("supersededBy")}
    labels = [f.label for f in info.fixtures if f.path in recommended and f.label]
    return labels if recommended and len(labels) == len(recommended) else []


def labelled_description(name: str, sizes: list[int], labels: list[str]) -> str:
    """The count and size range from the manifest, then as many labels as fit.

    It says "test" because that is the word people search with; the sizes are measured
    bytes, rounded by the same formatter as everywhere else on the site.
    """
    count = len(sizes)
    span = (
        f"from {human_bytes(min(sizes))} to {human_bytes(max(sizes))}"
        if count > 1
        else f"of {human_bytes(sizes[0])}"
    )
    head = f"{count} {name} test file{'' if count == 1 else 's'} {span}: "
    tail = ". Direct URLs, SHA-256 per file, CC0."
    shown: list[str] = []
    for text in labels:
        if len(head + ", ".join([*shown, text]) + tail) > DESCRIPTION_LIMIT:
            break
        shown.append(text)
    return head + ", ".join(shown) + tail


def human_bytes(count: int) -> str:
    for unit, size in (("GB", 10**9), ("MB", 10**6), ("KB", 10**3)):
        if count >= size:
            return f"{f'{count / size:.1f}'.removesuffix('.0')} {unit}"
    return f"{count} B"


#: What each outcome means to somebody testing a reader (docs/04 §1.3.1). Only
#: `must-fail` says failure is required; the other two say a reader that copes is right.
OUTCOME_NOTES = {
    "must-fail": "every conforming reader must refuse it",
    "may-recover": "part of it can still be read, and a reader that does is not wrong",
    "varies": "readers disagree, and neither outcome is guaranteed",
}


def edge_facts(props: dict[str, Any]) -> dict[str, str] | None:
    """The measured description of a broken file, for the format page (docs/04 §1.3.1).

    Read straight from the published props, so the page cannot say anything about a
    fixture that the validators did not measure on its bytes.
    """
    if "damage" not in props:
        return None
    outcome = str(props.get("outcome", ""))
    return {
        "damage": str(props["damage"]),
        "outcome": outcome,
        "note": OUTCOME_NOTES.get(outcome, ""),
        "compare_with": str(props.get("compare_with", "")),
        "derived_from": str(props.get("derived_from", "")),
    }


def key_props(props: dict[str, Any]) -> str:
    """At most four measured properties worth reading in a table cell."""
    shown: list[str] = []
    if "defect" in props:  # an edge case: what is wrong with it comes first
        shown.append(str(props["defect"]))
        if props.get("outcome"):
            shown.append(str(props["outcome"]))
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


def counted(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


#: The measured props a format page's lead line shows, in reading order.
FACTS: tuple[tuple[str, Callable[[Any], str]], ...] = (
    ("duration_ms", lambda v: f"{v / 1000:g} s"),
    ("vcodec", str),
    ("profile", str),
    ("level", lambda v: f"level {v}"),
    ("acodec", str),
    ("sample_rate", lambda v: f"{v / 1000:g} kHz"),
    ("channels", lambda v: counted(v, "channel")),
    ("segments", lambda v: counted(v, "segment")),
    ("target_duration_s", lambda v: f"{v} s target duration"),
    ("playlist_type", str),
    ("variants", lambda v: counted(v, "rendition")),
    ("resolutions", " and ".join),
    ("paragraphs", lambda v: counted(v, "paragraph")),
    ("words", lambda v: counted(v, "word")),
    ("rows", lambda v: counted(v, "row")),
    ("columns", lambda v: counted(v, "column")),
    ("mode", str),
    ("encoding", str),
    ("line_ending", lambda v: str(v).upper()),
    ("lines", lambda v: counted(v, "line")),
    ("entries", lambda v: f"{v:,} {'entry' if v == 1 else 'entries'}"),
    ("moov_at_end", lambda v: "moov at the end" if v else "moov first"),
    ("outcome", str),
)


def file_facts(entry: dict[str, Any]) -> str:
    """A fixture's link, size, media type and measured props as one Markdown line.

    Read from the manifest, so the numbers a page leads with are the measured ones: a size
    or duration typed into prose is a second copy that nobody re-measures.
    """
    facts = [
        f"[`{config.BASE_URL}{entry['path']}`](/{entry['path']})",
        sized(entry["bytes"]),
        f"`{entry['mime']}`",
    ]
    return " · ".join(facts + measured(entry))


def sized(count: int) -> str:
    """A fixture's size wherever a page or twin shows one: rounded, with the exact count.

    The rounding alone gives `bin/10mb-minus-1.bin`, `10mb.bin` and `10mb-plus-1.bin` one
    label, and those files exist for the one byte between them. The search box prints this
    string from `search-index.json` rather than formatting sizes a second way.
    """
    human = human_bytes(count)
    # Under a kilobyte the rounded figure is already the exact one: "586 B", not "586 bytes".
    return human if human == f"{count} B" else f"{human} ({count:,} bytes)"


def measured(entry: dict[str, Any]) -> list[str]:
    """A fixture's measured properties as short facts, in the order the pages show them."""
    props = entry.get("props") or {}
    size = [f"{props['width']}x{props['height']}"] if "width" in props and "height" in props else []
    return size + [show(props[name]) for name, show in FACTS if props.get(name) is not None]


def lead_files(text: str, source: str, entries: dict[str, dict[str, Any]]) -> str:
    """Replace each `<!-- file: PATH -->` line with that fixture's `file_facts`.

    ``entries`` is what ``source`` may name: a format page its own active files, a testing
    guide every active file. Anything else stops the build, so no page lists a stale file.
    """

    def facts(match: re.Match[str]) -> str:
        if match.group(1) not in entries:
            raise SiteError(f"{source} names {match.group(1)}, which it may not list")
        return file_facts(entries[match.group(1)])

    return FILE.sub(facts, text)


TWIN_TABLE = "| Path | Size | MIME | Properties |\n|---|---|---|---|\n"
#: File markers one after another, blank lines between: one table in a twin, not several.
MARKER_RUN = re.compile(r"^<!-- file: \S+ -->(?:\n\n?<!-- file: \S+ -->)*$", re.M)
#: A Markdown link to a site path, made absolute in a twin, which agents read without a base.
SITE_LINK = re.compile(r"\]\(/(?!/)")


def twin_row(entry: dict[str, Any]) -> str:
    cells = [
        f"[`{entry['path']}`]({config.BASE_URL}{entry['path']})",
        sized(entry["bytes"]),
        f"`{entry['mime']}`",
        ", ".join(measured(entry)),
    ]
    return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |\n"


def twin(
    page: Page,
    text: str,
    source: str,
    entries: dict[str, dict[str, Any]],
    *,
    table: list[dict[str, Any]] | None = None,
    superseded: list[dict[str, Any]] | None = None,
    index_url: str | None = None,
) -> str:
    """The page as Markdown (docs/04 §5b): its prose with each file marker expanded into a
    row of path, size, media type and measured props, then its file table if it has one.

    Every number comes from the manifest, as on the HTML page; a marker the page may not
    list stops the build here too.
    """

    def expand(match: re.Match[str]) -> str:
        paths = FILE.findall(match.group(0))
        for path in paths:
            if path not in entries:
                raise SiteError(f"{source} names {path}, which it may not list")
        return (TWIN_TABLE + "".join(twin_row(entries[path]) for path in paths)).rstrip("\n")

    prose = SITE_LINK.sub(f"]({config.BASE_URL}", MARKER_RUN.sub(expand, text)).strip()
    parts = [f"# {page.h1}", page.description, f"The page: <{page.canonical}>.", prose]
    if table:
        rows = "".join(twin_row(entry) for entry in table)
        parts.append(f"## Files\n\n{TWIN_TABLE}{rows}".rstrip("\n"))
    if superseded:
        parts.append(
            "## Superseded\n\n"
            + "\n".join(
                f"- `{e['path']}` is replaced by `{e['supersededBy']}`. The old URL still "
                "serves the same bytes."
                for e in superseded
            )
        )
    if index_url:
        parts.append(f"The same list as JSON: <{index_url}>.")
    return "\n\n".join(parts) + "\n"


def embed_snippet(family: str, url: str) -> str:
    if family == "images":
        return f'<img src="{url}" alt="">'
    if family == "video":
        return f'<video src="{url}" controls></video>'
    if family == "audio":
        return f'<audio src="{url}" controls></audio>'
    return f'<a href="{url}">download</a>'


def section(path: Path, heading: str) -> str:
    return section_text(path.read_text(encoding="utf-8"), heading, path.name)


def section_text(text: str, heading: str, name: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(heading):
            body: list[str] = []
            for following in lines[index + 1 :]:
                if HEADING.match(following):
                    break
                body.append(following)
            return "\n".join(body).strip("\n") + "\n"
    raise SiteError(f"{name} has no section starting {heading!r}")


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


#: `<!-- include: examples/verify.py -->` on a line of its own becomes that file, fenced.
INCLUDE = re.compile(r"^<!-- include: (\S+) -->$", re.M)
#: The fence language for each file a page may include.
FENCE = {".sh": "sh", ".py": "python", ".mjs": "javascript", ".go": "go", ".java": "java"}
#: `<!-- file: m4a/aac-30s.m4a -->` on a line of its own, in a format page, becomes that
#: fixture's link and measured facts, so the page can show the file before explaining it.
FILE = re.compile(r"^<!-- file: (\S+) -->$", re.M)


def content(root: Path, relative: str) -> str:
    """A content page, with any `include` replaced by the file it names.

    The snippets on `/docs/languages` are real files that CI executes. Including them at
    build time rather than pasting them in is what stops the page from drifting away from
    the code that is actually run — a page of examples nobody runs is the bug report a
    stranger files.
    """
    path = root / "site" / "content" / relative
    if not path.is_file():
        raise SiteError(f"site/content/{relative} is missing (docs/07 §5)")

    def embed(match: re.Match[str]) -> str:
        source = root / match.group(1)
        if not source.is_file():
            raise SiteError(f"{relative} includes {match.group(1)}, which does not exist")
        body = source.read_text(encoding="utf-8").rstrip()
        return f"```{FENCE.get(source.suffix, '')}\n{body}\n```"

    return INCLUDE.sub(embed, path.read_text(encoding="utf-8"))


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


def article(page: Page, *, modified: dt.date | None = None) -> list[dict[str, Any]]:
    node: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "TechArticle",
        "headline": page.h1,
        "description": page.description,
        "url": page.canonical,
    }
    if modified is not None:
        node["dateModified"] = modified.isoformat()
    return [node, breadcrumbs(page.crumbs, page.h1, page.canonical)]


def dataset(
    name: str,
    description: str,
    url: str,
    entries: list[dict[str, Any]],
    *,
    modified: dt.date | None,
) -> dict[str, Any]:
    """docs/04 §10: a page of files is a Dataset whose distribution is those files.

    `dateModified` is the page's date in `page-dates.json`, which the sitemap gives as
    `lastmod`; None leaves it out, for the undated rendering that date is hashed from.
    `contentSize` and `sha256` are the manifest's, so a crawler can tell the file it fetched
    is the one listed.
    """
    node: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": name,
        "description": description,
        "url": url,
        "license": config.LICENSE_URL,
        "isAccessibleForFree": True,
    }
    if modified is not None:
        node["dateModified"] = modified.isoformat()
    node["distribution"] = [
        {
            "@type": "DataDownload",
            "contentUrl": f"{config.BASE_URL}{e['path']}",
            "encodingFormat": e["mime"],
            "contentSize": f"{e['bytes']} bytes",
            "sha256": e["sha256"],
        }
        for e in entries
    ]
    return node


# --- pages ------------------------------------------------------------------------------------


#: A page's date by key: `page-dates.json`'s, or None for the undated rendering (docs/04 §7).
DateOf = Callable[[str], dt.date | None]


def format_pages(
    root: Path, manifest: Manifest, catalogs: dict[str, FormatCatalog], *, date_of: DateOf
) -> list[Page]:
    formats = sorted({entry["format"] for entry in manifest.entries})
    pages: list[Page] = []
    for fmt in formats:
        if fmt in RESERVED or fmt not in catalogs:
            raise SiteError(f"format {fmt!r} is reserved by the site or absent from the catalog")
        info = catalogs[fmt]
        entries = sorted(
            (e for e in manifest.entries if e["format"] == fmt), key=lambda e: e["path"]
        )
        served = [e for e in entries if e.get("status", "active") == "active"]
        # A superseded path is still served, but the page recommends its replacement and
        # names the old path below the table, so an embedded URL is never left unexplained.
        active = [e for e in served if not e.get("supersededBy")]
        superseded = [e for e in served if e.get("supersededBy")]
        rows = [
            {
                "path": e["path"],
                "name": e["path"].split("/", 1)[1],
                "url": f"{config.BASE_URL}{e['path']}",
                "size": sized(e["bytes"]),
                "props": key_props(e.get("props") or {}),
                "edge": edge_facts(e.get("props") or {}),
                "description": e["description"],
                "curl": f"curl -O {config.BASE_URL}{e['path']}",
                "embed": embed_snippet(info.family.value, f"{config.BASE_URL}{e['path']}"),
            }
            for e in active
        ]
        plural = "" if len(active) == 1 else "s"
        title = f"{info.seo_title} · loremfile.dev"
        description = (
            f"{len(active)} sample {label(fmt)} file{plural} with stable URLs you can "
            "hotlink. No signup, no keys, CC0."
        )
        # The labelled shape, only where every recommended file has a label (docs/05 §1
        # rule 9): ogg, tiff and arrow from 1.9.0, the twelve demand formats from 2026-10-22.
        labels = page_labels(info, served)
        if labels:
            title = labelled_title(label(fmt), labels, title_head(fmt))
            description = labelled_description(label(fmt), [e["bytes"] for e in active], labels)
        page = Page(
            key=fmt,
            h1=info.seo_title,
            title=title,
            description=description,
            template="format.html",
            crumbs=[("Home", "/"), ("Formats", "/formats")],
            context={
                "format": fmt,
                "label": label(fmt),
                "intro": trusted(
                    markdown.render(
                        lead_files(
                            content(root, f"formats/{fmt}.md"),
                            f"site/content/formats/{fmt}.md",
                            {e["path"]: e for e in active},
                        )
                    )
                ),
                "rows": rows,
                "removed": [e for e in entries if e.get("status") == "removed"],
                "superseded": superseded,
                "related": [
                    {"format": other, "label": label(other)}
                    for other in info.related
                    if other in formats
                ],
                "index_url": routes.absolute_url(routes.format_index_key(fmt)),
            },
        )
        page.jsonld = [
            dataset(
                info.seo_title,
                " ".join(info.description.split()),
                page.canonical,
                active,
                modified=date_of(fmt),
            ),
            breadcrumbs(page.crumbs, label(fmt), page.canonical),
        ]
        index_url = routes.absolute_url(routes.format_index_key(fmt))
        page.alternates = [
            ("application/json", index_url),
            ("text/markdown", routes.absolute_url(routes.twin_key(fmt))),
        ]
        page.twin = twin(
            page,
            content(root, f"formats/{fmt}.md"),
            f"site/content/formats/{fmt}.md",
            {e["path"]: e for e in active},
            table=active,
            superseded=superseded,
            index_url=index_url,
        )
        pages.append(page)
    return pages


def families(manifest: Manifest, catalogs: dict[str, FormatCatalog]) -> list[dict[str, Any]]:
    counts = Counter(entry["format"] for entry in manifest.current)
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


def home_page(
    root: Path,
    manifest: Manifest,
    catalogs: dict[str, FormatCatalog],
    tasks: list[tuple[str, str, str]],
) -> Page:
    by_path = {entry["path"]: entry for entry in manifest.current}
    missing = [path for path in POPULAR if path not in by_path]
    if missing:
        raise SiteError(f"popular paths not in the manifest: {', '.join(missing)} (docs/05 §8)")
    return Page(
        key="index.html",
        h1="Sample files you can hotlink or download",
        title="loremfile.dev: sample files you can hotlink or download",
        description=(
            "Free, CC0 sample files with stable URLs you can hotlink, or download for offline "
            "tests: PDFs, images, audio, video, office and data files. No signup."
        ),
        template="home.html",
        context={
            "pitch": trusted(markdown.render(content(root, "home.md"))),
            "families": families(manifest, catalogs),
            "popular": [
                {
                    "path": path,
                    "url": f"{config.BASE_URL}{path}",
                    "size": sized(by_path[path]["bytes"]),
                    "description": by_path[path]["description"],
                }
                for path in POPULAR
            ],
            "count": len(manifest.current),
            "tasks": tasks,
        },
        jsonld=[
            {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": config.SITE_HOST,
                "url": config.BASE_URL,
                "description": "Free, CC0 sample files and test fixtures you can hotlink or "
                "download.",
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
    active = manifest.current
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
    page = Page(
        key="formats",
        h1="All formats",
        description=f"Every format on loremfile.dev: {len(rows)} formats, {len(active)} files.",
        template="formats.html",
        crumbs=[("Home", "/")],
        context={"rows": rows},
    )
    page.jsonld = [
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": page.h1,
            "description": page.description,
            "url": page.canonical,
            "mainEntity": {
                "@type": "ItemList",
                "numberOfItems": len(rows),
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": position,
                        "name": row["label"],
                        "url": routes.absolute_url(row["format"]),
                    }
                    for position, row in enumerate(rows, start=1)
                ],
            },
        },
        breadcrumbs(page.crumbs, page.h1, page.canonical),
    ]
    return page


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


def testing_pages(root: Path, manifest: Manifest, *, date_of: DateOf) -> list[Page]:
    """Guides by job: prose that names files and says why, their facts from the manifest."""
    active = {entry["path"]: entry for entry in manifest.current}
    crumbs = [("Home", "/"), ("Testing", "/testing")]
    pages: list[Page] = []
    for key, title, description, source in TESTING:
        text = content(root, source)
        named = list(dict.fromkeys(FILE.findall(text)))
        body = markdown.render(lead_files(text, f"site/content/{source}", active))
        page = Page(
            key,
            title,
            description,
            "doc.html",
            title=f"{title} · loremfile.dev",
            crumbs=crumbs,
            context={"body": trusted(body)},
        )
        listed = [active[path] for path in named]
        page.jsonld = [
            dataset(title, description, page.canonical, listed, modified=date_of(key)),
            breadcrumbs(crumbs, title, page.canonical),
        ]
        page.twin = twin(page, text, f"site/content/{source}", active)
        page.alternates = [("text/markdown", routes.absolute_url(routes.twin_key(key)))]
        pages.append(page)
    index = Page(
        "testing",
        "Testing guides",
        "Sample files chosen for a job rather than a format: uploads, parsers and error "
        "handling, media playback and seeking.",
        "doc.html",
        crumbs=[("Home", "/")],
        context={"body": trusted(""), "items": guides(pages)},
    )
    index.jsonld = article(index)
    return [index, *pages]


def guides(pages: list[Page]) -> list[tuple[str, str, str]]:
    return [(f"/{p.key}", p.h1, p.description) for p in pages if p.key.startswith("testing/")]


#: The source of every legal page (docs/13), relative to the repository root.
LEGAL_SOURCE = "docs/13-legal-and-policy.md"
#: The legal pages that show when their text last changed; the Impressum is four fixed lines.
DATED_LEGAL = ("legal/license", "legal/terms", "legal/privacy")
#: Spelled out rather than `%B`, which follows the locale and would change the bytes.
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise SiteError("git is not on PATH")
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [executable, *args], cwd=root, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise SiteError(f"git {args[0]} failed: {done.stderr.strip()}")
    return done.stdout


def legal_dates(root: Path, committed: dt.datetime) -> dict[str, dt.date]:
    """Each dated legal page's last change: the commit that introduced its published text.

    Walks back through the commits that touched docs/13 while the page's quoted text stays
    what the working tree holds; the oldest of that run introduced it. Text that differs from
    HEAD is dated at the build's clock. A shallow clone would end the walk at its boundary
    and date every page wrongly, so it is refused: every job that builds the site fetches
    full history.
    """
    if _git(root, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise SiteError("a shallow clone cannot date the legal pages; fetch full history")
    headings = {key: heading for key, heading, _ in LEGAL}
    source = (root / LEGAL_SOURCE).read_text(encoding="utf-8")
    history = [
        line.split(" ", 1)
        for line in _git(root, "log", "--format=%H %cI", "--", LEGAL_SOURCE).splitlines()
    ]
    versions: dict[str, str] = {}
    dates: dict[str, dt.date] = {}
    for key in DATED_LEGAL:
        current = quoted(section_text(source, headings[key], LEGAL_SOURCE))
        dates[key] = committed.astimezone(dt.UTC).date()
        for sha, when in history:
            if sha not in versions:
                versions[sha] = _git(root, "show", f"{sha}:{LEGAL_SOURCE}")
            try:
                then = quoted(section_text(versions[sha], headings[key], LEGAL_SOURCE))
            except SiteError:
                break
            if then != current:
                break
            dates[key] = dt.datetime.fromisoformat(when).astimezone(dt.UTC).date()
    return dates


def updated_line(day: dt.date) -> str:
    shown = f"{day.day} {MONTHS[day.month - 1]} {day.year}"
    return f'<p>Last updated <time datetime="{day.isoformat()}">{shown}</time></p>\n'


def legal_pages(root: Path, committed: dt.datetime) -> list[Page]:
    source = root / LEGAL_SOURCE
    crumbs = [("Home", "/"), ("Legal", "/legal")]
    dates = legal_dates(root, committed)
    pages: list[Page] = []
    for key, heading, description in LEGAL:
        title, text = quoted(section(source, heading))
        body = markdown.render(text, breaks=key == "legal/imprint")
        day = dates.get(key)
        page = Page(
            key,
            title,
            description,
            "legal.html",
            crumbs=crumbs,
            context={"body": trusted(body if day is None else updated_line(day) + body)},
            robots=routes.LEGAL_ROBOTS if key in routes.LEGAL_KEYS else None,
        )
        page.jsonld = article(page, modified=day) if page.listed else []
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
    page = Page(
        "changelog",
        "Changelog",
        "Every catalog version of loremfile.dev and what it added.",
        "changelog.html",
        crumbs=[("Home", "/")],
        context={"body": trusted(markdown.render(text, source="CHANGELOG.md"))},
    )
    page.jsonld = article(page)
    return page


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
        {
            "path": e["path"],
            "bytes": e["bytes"],
            "size": sized(e["bytes"]),
            "description": e["description"],
        }
        for e in sorted(manifest.current, key=lambda e: e["path"])
    ]
    return (json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def llms(
    manifest: Manifest,
    catalogs: dict[str, FormatCatalog],
    tasks: list[tuple[str, str, str]],
    *,
    full: bool,
) -> bytes:
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
        # Patterns, never absolute URLs with braces: a crawler that reads this text fetches
        # `/{format}/{name}` literally and gets a 404 (2026-10-23).
        f"- Every fixture: {{format}}/{{name}} under the site root, for example "
        f"{base}pdf/a4-1page.pdf (the manifest lists every path)",
        f"- Machine-readable list of everything: {base}manifest.json (JSON, includes sha256, "
        "bytes, mime, measured properties)",
        f"- Per-format lists: {{format}}/index.json, for example {base}pdf/index.json",
        "- Any format or guide page as Markdown: append /index.md to its URL, for example "
        f"{base}pdf/index.md or {base}testing/uploads/index.md",
        f"- Verify: {base}sha256sums.txt",
        "- Verify from a page alone: the JSON-LD Dataset on every format and guide page gives "
        "each file's contentSize and sha256, so a download can be checked without the manifest",
        f"- Working examples in five languages: {base}docs/languages",
        "- MCP server for agents: `npx -y loremfile mcp` or `uvx loremfile mcp`, three read-only "
        f"tools (list_fixtures, describe_fixture, verify_file): {base}docs/mcp",
        "",
        "## Formats",
    ]
    for group in families(manifest, catalogs):
        links = ", ".join(
            f"[{item['format']}]({base}{item['format']}) ({item['count']})"
            for item in group["formats"]
        )
        lines.append(f"- {group['label']}: {links}")
    lines += ["", "## Testing guides"]
    lines += [f"- [{title}]({base}{href[1:]}): {text}" for href, title, text in tasks]
    lines += [
        "",
        "## Rules",
        "- Query strings are ignored. Stay under 30 requests/second per IP.",
        f"- License: CC0 1.0 for all fixtures. Source: {config.SOURCE_URL}",
    ]
    if full:
        lines += ["", "## Fixtures"]
        active = sorted(manifest.current, key=lambda e: e["path"])
        for fmt in sorted({e["format"] for e in active}):
            lines += ["", f"### {fmt}", "", "| Path | Bytes | Description | Properties |"]
            lines.append("|---|---|---|---|")
            for e in (e for e in active if e["format"] == fmt):
                cells = (e["description"], key_props(e.get("props") or {}))
                description, props = (cell.replace("|", "\\|") for cell in cells)
                lines.append(f"| {e['path']} | {e['bytes']} | {description} | {props} |")
    return ("\n".join(lines) + "\n").encode()


#: Indexable pages the sitemap leaves out (2026-10-16). Indexed-page count is the RISK-18
#: tripwire (docs/17), and a sitemap that lists pages nobody wants in search makes that
#: count wrong by construction. They stay indexable and linked from every footer; this
#: only stops asking for them. The two operator pages are out anyway, as noindex.
NOT_IN_SITEMAP = frozenset({"legal", "legal/license", "legal/terms"})


def in_sitemap(page: Page) -> bool:
    return page.listed and page.key not in NOT_IN_SITEMAP


def sitemap(pages: list[Page], dates: page_dates.Record) -> bytes:
    """Each page's `lastmod` is the day its content last changed (docs/04 §7)."""
    rows = sorted((page.canonical, dates[page.key].date) for page in pages if in_sitemap(page))
    body = "".join(
        f"  <url><loc>{xml_escape(url)}</loc><lastmod>{day.isoformat()}</lastmod></url>\n"
        for url, day in rows
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}</urlset>\n"
    ).encode()


def api_catalog(formats: list[str]) -> bytes:
    """RFC 9727: the data files an agent can use, each with the documentation that explains it.

    Only machine-readable data is listed, never a page, so neither legal page can appear.
    """
    doc = [{"href": routes.absolute_url("llms.txt"), "type": "text/plain"}]
    schema = {
        "href": routes.absolute_url("schema/manifest-v1.json"),
        "type": "application/schema+json",
    }
    linkset = [
        {
            "anchor": routes.absolute_url("manifest.json"),
            "service-desc": [schema],
            "service-doc": doc,
        },
        {"anchor": routes.absolute_url("sha256sums.txt"), "service-doc": doc},
        *(
            {"anchor": routes.absolute_url(routes.format_index_key(fmt)), "service-doc": doc}
            for fmt in formats
        ),
    ]
    return (json.dumps({"linkset": linkset}, indent=2) + "\n").encode()


#: One skill, published as its own `SKILL.md` (Agent Skills Discovery v0.2.0, `type: skill-md`).
AGENT_SKILL = "find-and-verify-fixtures"
AGENT_SKILLS_SCHEMA = "https://schemas.agentskills.io/discovery/0.2.0/schema.json"


def agent_skill_key(name: str) -> str:
    return f".well-known/agent-skills/{name}/SKILL.md"


def agent_skills(root: Path) -> dict[str, bytes]:
    """The skill file and the index that lists it, with the SHA-256 of the file's bytes."""
    skill = (root / "site" / "agent-skills" / AGENT_SKILL / "SKILL.md").read_bytes()
    front = re.match(r"---\nname: (\S+)\ndescription: (.+)\n---\n", skill.decode("utf-8"))
    if front is None or front.group(1) != AGENT_SKILL:
        raise SiteError(f"{AGENT_SKILL}/SKILL.md: frontmatter must name {AGENT_SKILL}")
    index = {
        "$schema": AGENT_SKILLS_SCHEMA,
        "skills": [
            {
                "name": AGENT_SKILL,
                "type": "skill-md",
                "description": front.group(2),
                "url": routes.public_path(agent_skill_key(AGENT_SKILL)),
                "digest": f"sha256:{sha256(skill)}",
            }
        ],
    }
    return {
        agent_skill_key(AGENT_SKILL): skill,
        routes.AGENT_SKILLS_INDEX_KEY: (json.dumps(index, indent=2) + "\n").encode(),
    }


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


def site_pages(
    root: Path,
    manifest: Manifest,
    catalogs: dict[str, FormatCatalog],
    *,
    committed: dt.datetime,
    date_of: DateOf,
) -> list[Page]:
    """Every page a build renders, in the order `build` writes them."""
    testing = testing_pages(root, manifest, date_of=date_of)
    return [
        home_page(root, manifest, catalogs, guides(testing)),
        *format_pages(root, manifest, catalogs, date_of=date_of),
        formats_page(manifest, catalogs),
        *testing,
        *doc_pages(root),
        *legal_pages(root, committed),
        changelog_page(root),
        status_page(),
    ]


def build(
    out: Path,
    *,
    root: Path,
    committed: dt.datetime,
    previous: page_dates.Record | None = None,
) -> BuildReport:
    """Render the site into `out`. `previous` is the page-dates record to date pages from;
    None reads the committed one. A page whose content changed is dated `committed`."""
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
    if previous is None:
        previous = page_dates.load(root / page_dates.FILE)
    # Hashed with no date at all, so neither a page's own date nor another's can move it.
    undated = site_pages(root, manifest, catalogs, committed=committed, date_of=lambda _: None)
    hashes = {p.key: sha256(render_page(env, p, site)) for p in undated if in_sitemap(p)}
    dates = page_dates.update(previous, hashes, committed.date())

    def date_of(key: str) -> dt.date:
        if key not in dates:
            raise SiteError(f"{key}: a dated page that the sitemap does not list")
        return dates[key].date

    pages = site_pages(root, manifest, catalogs, committed=committed, date_of=date_of)
    for page in pages:
        if page.key.endswith(".html") and page.key != "index.html":
            raise SiteError(
                f"{page.key}: only the root page key may end in .html (routes.disk_path)"
            )
        if page.key in files:
            raise SiteError(f"two outputs claim the key {page.key!r}")
        files[page.key] = render_page(env, page, site)
        if page.twin is not None:
            files[routes.twin_key(page.key)] = page.twin.encode("utf-8")
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
            "llms.txt": llms(manifest, catalogs, guides(pages), full=False),
            "llms-full.txt": llms(manifest, catalogs, guides(pages), full=True),
            "sitemap.xml": sitemap(pages, dates),
            "robots.txt": ROBOTS_TXT.encode(),
            ".well-known/security.txt": security_txt(committed),
            routes.INDEXNOW_KEY_FILE: config.INDEXNOW_KEY.encode("utf-8"),
            routes.API_CATALOG_KEY: api_catalog(formats),
            **agent_skills(root),
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
    return BuildReport(
        keys=len(files),
        pages=len(pages),
        bytes=sum(map(len, files.values())),
        dates=dates,
        stale=page_dates.stale(previous, dates),
    )
