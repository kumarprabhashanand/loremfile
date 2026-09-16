"""Web fixtures — html, css, js, webmanifest, srt, vtt, ipynb and har (docs/05 §3.6).

Everything here is inert by design. The one script is a `console.log`, the HTML carries no
event handlers and no external references, and the edge serves all of it with a sandbox
CSP (`08` §5.3), so opening a fixture in a browser runs nothing. The notebook and the HAR
are JSON with every timestamp fixed, because both formats normally record when they ran.
"""

from __future__ import annotations

import json

from loremfile.generators.base import GeneratorContext, generator
from loremfile.util import lorem

#: Every timestamp in this module. The formats that carry one would otherwise record the
#: build time, and the fixture's hash would move.
TIMESTAMP = "2020-01-01T00:00:00Z"
LANGUAGES = {
    "el": "Greek",
    "ru": "Cyrillic",
    "ar": "Arabic",
    "he": "Hebrew",
    "hi": "Devanagari",
    "th": "Thai",
    "ja": "CJK",
    "ko": "Hangul",
}


def _document(title: str, body: str, *, lang: str = "en", head: str = "") -> bytes:
    return (
        "<!doctype html>\n"
        f'<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{title}</title>\n{head}</head>\n<body>\n{body}</body>\n</html>\n"
    ).encode()


@generator()
def html_basic(ctx: GeneratorContext) -> bytes:
    """A minimal, valid HTML5 document: a heading and two paragraphs."""
    rng = ctx.rng
    body = (
        f"<h1>A basic document</h1>\n<p>{lorem.paragraph(rng)}</p>\n<p>{lorem.paragraph(rng)}</p>\n"
    )
    return _document("A basic document", body)


@generator()
def html_all_elements(ctx: GeneratorContext) -> bytes:
    """The elements a parser, sanitiser or converter is expected to handle.

    Semantic sections, a table, a form with no action, lists, a figure, and media elements
    pointing at published fixtures rather than at anything external.
    """
    rng = ctx.rng
    rows = "\n".join(
        f"    <tr><td>{index}</td><td>{lorem.sentence(rng, 3, 6)}</td></tr>"
        for index in range(1, 6)
    )
    body = f"""<header><h1>Every common element</h1></header>
<nav><ul><li><a href="#prose">Prose</a></li><li><a href="#data">Data</a></li></ul></nav>
<main>
<section id="prose">
<h2>Prose</h2>
<p>{lorem.paragraph(rng)}</p>
<blockquote><p>{lorem.sentence(rng)}</p></blockquote>
<p><strong>Bold</strong>, <em>italic</em>, <code>code</code>
and <abbr title="abbreviation">abbr</abbr>.</p>
<ul><li>{lorem.sentence(rng, 3, 6)}</li><li>{lorem.sentence(rng, 3, 6)}</li></ul>
<ol><li>{lorem.sentence(rng, 3, 6)}</li><li>{lorem.sentence(rng, 3, 6)}</li></ol>
<dl><dt>Term</dt><dd>{lorem.sentence(rng, 3, 6)}</dd></dl>
</section>
<section id="data">
<h2>Data</h2>
<table>
  <caption>A small table</caption>
  <thead><tr><th scope="col">#</th><th scope="col">Text</th></tr></thead>
  <tbody>
{rows}
  </tbody>
</table>
<form>
  <label for="name">Name</label>
  <input id="name" type="text" name="name">
  <label for="colour">Colour</label>
  <select id="colour" name="colour"><option>Red</option><option>Blue</option></select>
  <button type="button">Does nothing</button>
</form>
</section>
<section id="media">
<h2>Media</h2>
<figure>
  <img src="https://loremfile.dev/png/640x480.png" alt="A colour-bar test card"
       width="640" height="480">
  <figcaption>{lorem.sentence(rng, 4, 8)}</figcaption>
</figure>
<video src="https://loremfile.dev/mp4/720p-5s.mp4" controls width="640" height="360"></video>
<audio src="https://loremfile.dev/mp3/sine-440hz-3s.mp3" controls></audio>
</section>
</main>
<footer><p>{lorem.sentence(rng)}</p></footer>
"""
    return _document("Every common element", body)


@generator()
def html_inline_css(ctx: GeneratorContext) -> bytes:
    """A document whose styles live in a `<style>` block, not in an external sheet."""
    style = (
        "<style>\n"
        "body { font-family: system-ui, sans-serif; margin: 2rem; color: #0f172a; }\n"
        "h1 { font-size: 2rem; }\n"
        "p { max-width: 40em; line-height: 1.6; }\n"
        ".card { border: 1px solid #e2e8f0; border-radius: 8px; padding: 1rem; }\n"
        "</style>\n"
    )
    rng = ctx.rng
    body = f'<h1>Inline styles</h1>\n<div class="card"><p>{lorem.paragraph(rng)}</p></div>\n'
    return _document("Inline styles", body, head=style)


@generator()
def html_inline_js(ctx: GeneratorContext) -> bytes:
    """A document with one inline script. It logs a line and does nothing else.

    No event handler attributes and no network access: the content policy refuses those,
    and the edge serves this file with a sandbox CSP that blocks scripts anyway (`03` §4.2).
    """
    script = '<script>\nconsole.log("loremfile: this script only logs.");\n</script>\n'
    rng = ctx.rng
    body = f"<h1>Inline script</h1>\n<p>{lorem.paragraph(rng)}</p>\n{script}"
    return _document("Inline script", body)


@generator()
def css_basic(_ctx: GeneratorContext) -> bytes:
    """A small stylesheet using the features a parser has to handle."""
    return b""":root {
  --ink: #0f172a;
  --paper: #ffffff;
  --accent: #1d4ed8;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}

h1, h2 { line-height: 1.2; }

a { color: var(--accent); }

.grid {
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
}

@media (prefers-color-scheme: dark) {
  :root { --ink: #e2e8f0; --paper: #0b1120; --accent: #93c5fd; }
}

@supports (display: grid) {
  .fallback { display: none; }
}
"""


@generator()
def js_hello(_ctx: GeneratorContext) -> bytes:
    """One script that logs a line. Nothing here reaches the network or the DOM."""
    return (
        b"// The only script in this catalog. It logs one line and returns.\n"
        b"function hello(name) {\n"
        b'  return "Hello, " + name + "!";\n'
        b"}\n"
        b"\n"
        b'console.log(hello("loremfile"));\n'
    )


@generator()
def site_webmanifest(_ctx: GeneratorContext) -> bytes:
    """A web app manifest, the JSON a browser reads for install metadata."""
    document = {
        "name": "loremfile fixtures",
        "short_name": "loremfile",
        "description": "A sample web app manifest for testing parsers.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#1d4ed8",
        "icons": [
            {
                "src": "https://loremfile.dev/png/100x100.png",
                "sizes": "100x100",
                "type": "image/png",
            },
            {
                "src": "https://loremfile.dev/png/640x480.png",
                "sizes": "640x480",
                "type": "image/png",
            },
        ],
        "lang": "en",
        "dir": "ltr",
    }
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _timecode(seconds: float, *, comma: bool) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    whole = int(secs)
    millis = round((secs - whole) * 1000)
    separator = "," if comma else "."
    return f"{int(hours):02d}:{int(minutes):02d}:{whole:02d}{separator}{millis:03d}"


def _cues(
    ctx: GeneratorContext, count: int, *, script: str | None = None
) -> list[tuple[float, float, str]]:
    rng = ctx.rng
    cues = []
    for index in range(count):
        start = index * 3.0
        text = lorem.pseudo_text(rng, script, 6) if script else lorem.sentence(rng, 4, 10)
        cues.append((start, start + 2.5, text))
    return cues


@generator()
def srt(ctx: GeneratorContext, *, count: int = 3, script: str | None = None) -> bytes:
    """SubRip subtitles: numbered cues, comma-separated milliseconds, CRLF line endings."""
    blocks = []
    for index, (start, end, text) in enumerate(_cues(ctx, count, script=script), start=1):
        blocks.append(
            f"{index}\r\n{_timecode(start, comma=True)} --> "
            f"{_timecode(end, comma=True)}\r\n{text}\r\n"
        )
    return "\r\n".join(blocks).encode("utf-8") + b"\r\n"


@generator()
def vtt(ctx: GeneratorContext, *, count: int = 3) -> bytes:
    """WebVTT: the `WEBVTT` header, a blank line, then cues with dotted milliseconds."""
    blocks = [
        f"{_timecode(start, comma=False)} --> {_timecode(end, comma=False)}\n{text}\n"
        for start, end, text in _cues(ctx, count)
    ]
    return ("WEBVTT\n\n" + "\n".join(blocks)).encode("utf-8")


@generator()
def ipynb(ctx: GeneratorContext) -> bytes:
    """A Jupyter notebook with outputs already stored, and no execution timestamps."""
    rng = ctx.rng
    document = {
        "cells": [
            {
                "cell_type": "markdown",
                "id": "cell-markdown",
                "metadata": {},
                "source": ["# A sample notebook\n", "\n", f"{lorem.sentence(rng)}\n"],
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "id": "cell-code",
                "metadata": {},
                "outputs": [
                    {
                        "data": {"text/plain": ["42"]},
                        "execution_count": 1,
                        "metadata": {},
                        "output_type": "execute_result",
                    }
                ],
                "source": ["answer = 6 * 7\n", "answer\n"],
            },
            {
                "cell_type": "code",
                "execution_count": 2,
                "id": "cell-stdout",
                "metadata": {},
                "outputs": [{"name": "stdout", "output_type": "stream", "text": ["loremfile\n"]}],
                "source": ['print("loremfile")\n'],
            },
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12.14"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return (json.dumps(document, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


@generator()
def har(ctx: GeneratorContext) -> bytes:
    """An HTTP Archive of three requests, with fixed times so the bytes never move."""
    rng = ctx.rng
    entries = []
    for index, (path, mime, size) in enumerate(
        (
            ("/", "text/html; charset=utf-8", 2048),
            ("/assets/site.css", "text/css; charset=utf-8", 4096),
            ("/png/100x100.png", "image/png", 1024),
        )
    ):
        entries.append(
            {
                "startedDateTime": TIMESTAMP,
                "time": 12 + index,
                "request": {
                    "method": "GET",
                    "url": f"https://loremfile.dev{path}",
                    "httpVersion": "HTTP/2",
                    "headers": [{"name": "accept", "value": "*/*"}],
                    "queryString": [],
                    "cookies": [],
                    "headersSize": -1,
                    "bodySize": 0,
                },
                "response": {
                    "status": 200,
                    "statusText": "OK",
                    "httpVersion": "HTTP/2",
                    "headers": [{"name": "content-type", "value": mime}],
                    "cookies": [],
                    "content": {"size": size, "mimeType": mime},
                    "redirectURL": "",
                    "headersSize": -1,
                    "bodySize": size,
                },
                "cache": {},
                "timings": {"send": 0, "wait": 10 + index, "receive": 2},
            }
        )
    document = {
        "log": {
            "version": "1.2",
            "creator": {"name": "loremfile fixtures", "version": "1.0"},
            "pages": [
                {
                    "startedDateTime": TIMESTAMP,
                    "id": "page_1",
                    "title": f"loremfile.dev — {lorem.sentence(rng, 3, 5)}",
                    "pageTimings": {"onContentLoad": 30, "onLoad": 60},
                }
            ],
            "entries": entries,
        }
    }
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
