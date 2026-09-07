"""Text fixtures — ``txt/``, ``md/``, ``log/``, ``ini/`` (docs/05 §3.6).

Sizes here are **exact**, not approximate: a size-named text fixture is cut at a word or
line boundary and padded with spaces before the final newline, so the file still reads as
text and still weighs precisely what its name claims (docs/05 §6).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from loremfile.generators.base import GeneratorContext, generator
from loremfile.util import lorem
from loremfile.util.sizing import pad_to

#: Byte-order marks, by the encoding whose name the fixture carries.
BOMS = {
    "utf-8": b"\xef\xbb\xbf",
    "utf-16le": b"\xff\xfe",
    "utf-16be": b"\xfe\xff",
    "utf-32le": b"\xff\xfe\x00\x00",
}


def _lorem_bytes(ctx: GeneratorContext, target: int) -> bytes:
    """Enough lorem text to fill ``target`` bytes, cut at a word boundary."""
    rng = ctx.rng
    chunks: list[str] = []
    size = 0
    while size < target + 1000:
        block = lorem.text(rng, 5, opening=not chunks)
        chunks.append(block)
        size += len(block.encode()) + 2
    text = "\n\n".join(chunks)
    encoded = text.encode("utf-8")[:target]
    # Cut back to the last whitespace so the file never ends mid-word.
    cut = encoded.rfind(b" ")
    return encoded[:cut] if cut > 0 else encoded


@generator()
def lorem_sized(ctx: GeneratorContext, *, size: int) -> bytes:
    """Lorem paragraphs padded to exactly ``size`` bytes, ending with a newline."""
    return pad_to(_lorem_bytes(ctx, size), size)


@generator()
def lines(ctx: GeneratorContext, *, count: int = 100, line_ending: str = "lf") -> bytes:
    """``count`` lorem lines with the given ending: lf, crlf, cr or mixed."""
    endings = {"lf": "\n", "crlf": "\r\n", "cr": "\r"}
    rng = ctx.rng
    body = [lorem.sentence(rng) for _ in range(count)]
    if line_ending == "mixed":
        cycle = ("\n", "\r\n", "\r")
        return "".join(line + cycle[i % 3] for i, line in enumerate(body)).encode()
    if line_ending not in endings:
        raise ValueError(f"unknown line_ending '{line_ending}'")
    return "".join(line + endings[line_ending] for line in body).encode()


@generator()
def encoded(
    ctx: GeneratorContext,
    *,
    encoding: str,
    bom: bool = False,
    script: str | None = None,
    paragraphs: int = 3,
) -> bytes:
    """Lorem, or native-script pseudo-text, in a specific encoding.

    ``script`` picks a character inventory so the bytes actually exercise the charset:
    ``shift-jis.txt`` is only a real test if it contains kanji.
    """
    rng = ctx.rng
    if script:
        blocks = [lorem.pseudo_text(rng, script, 60) for _ in range(paragraphs)]
        text = "\n\n".join(blocks) + "\n"
    else:
        text = lorem.text(rng, paragraphs) + "\n"
    prefix = BOMS[encoding.lower()] if bom else b""
    return prefix + text.encode(encoding)


@generator()
def multilingual(ctx: GeneratorContext) -> bytes:
    """One line per script, plus emoji, combining marks, bidi controls and odd spaces.

    Deliberately the hardest plain-text file the catalog has: if a pipeline survives
    this, its Unicode handling is real.
    """
    rng = ctx.rng
    out = [f"Latin: {lorem.sentence(rng)}"]
    for script in (
        "greek",
        "cyrillic",
        "arabic",
        "hebrew",
        "devanagari",
        "thai",
        "hanzi",
        "hiragana",
        "hangul_jamo",
    ):
        out.append(f"{script.capitalize()}: {lorem.pseudo_text(rng, script, 8)}")
    out.append(f"Emoji: {lorem.emoji_run(rng, 12)}")
    out.append("Combining marks: a\u0301 e\u0300 o\u0302 n\u0303 u\u0308 c\u0327")
    # Written as escapes on purpose: literal bidi controls in source are how Trojan
    # Source attacks hide, and ruff rejects them. The fixture still contains the real
    # characters, which is what makes it worth testing against.
    out.append("Bidi controls: \u202aLTR\u202c \u202bRTL\u202c \u2066isolate\u2069")
    out.append("Odd spaces: NBSP[\u00a0] ZWSP[\u200b] THIN[\u2009] IDEOGRAPHIC[\u3000]")
    return ("\n".join(out) + "\n").encode("utf-8")


@generator()
def emoji_only(ctx: GeneratorContext, *, count: int = 200) -> bytes:
    """Nothing but emoji sequences, including ZWJ families and skin tones."""
    return (lorem.emoji_run(ctx.rng, count) + "\n").encode("utf-8")


@generator()
def one_long_line(ctx: GeneratorContext, *, size: int) -> bytes:
    """A single line of exactly ``size`` bytes, newline included.

    Line-oriented tools that read a whole line into memory meet their match here.
    """
    body = _lorem_bytes(ctx, size).replace(b"\n", b" ")
    return pad_to(body, size)


@generator()
def nginx_access_log(ctx: GeneratorContext, *, count: int = 1000) -> bytes:
    """Combined-log-format lines with fixed timestamps and documentation IPs.

    Addresses come from the RFC 5737 documentation ranges, so no real host is named.
    """
    rng = ctx.rng
    paths = [
        "/",
        "/index.html",
        "/api/v1/items",
        "/assets/app.css",
        "/favicon.ico",
        "/pdf/a4-3pages.pdf",
        "/login",
        "/search?q=lorem",
    ]
    agents = ["Mozilla/5.0 (X11; Linux x86_64)", "curl/8.7.1", "python-requests/2.34.2"]
    start = datetime(2020, 1, 1, tzinfo=UTC)
    out = []
    for index in range(count):
        stamp = (start + timedelta(seconds=index * 7)).strftime("%d/%b/%Y:%H:%M:%S +0000")
        ip = f"192.0.2.{rng.randint(1, 254)}"
        method = rng.choice(["GET", "GET", "GET", "POST", "HEAD"])
        path = rng.choice(paths)
        status = rng.choices([200, 200, 200, 301, 304, 404, 500], k=1)[0]
        size = rng.randint(120, 90_000)
        out.append(
            f'{ip} - - [{stamp}] "{method} {path} HTTP/1.1" {status} {size} '
            f'"-" "{rng.choice(agents)}"'
        )
    return ("\n".join(out) + "\n").encode()


@generator()
def json_lines_log(ctx: GeneratorContext, *, count: int = 1000) -> bytes:
    """One JSON object per line — the shape most log shippers expect."""
    rng = ctx.rng
    levels = ["debug", "info", "info", "info", "warn", "error"]
    services = ["api", "worker", "scheduler", "gateway"]
    start = datetime(2020, 1, 1, tzinfo=UTC)
    out = []
    for index in range(count):
        record = {
            "ts": (start + timedelta(milliseconds=index * 250)).isoformat().replace("+00:00", "Z"),
            "level": rng.choice(levels),
            "service": rng.choice(services),
            "trace_id": ctx.stream(16)[:8].hex(),
            "msg": lorem.sentence(rng, 3, 8),
            "duration_ms": rng.randint(1, 4000),
        }
        out.append(json.dumps(record, separators=(",", ":"), ensure_ascii=False))
    return ("\n".join(out) + "\n").encode("utf-8")


@generator()
def ini_config(ctx: GeneratorContext) -> bytes:
    """A config file covering sections, comments, quoting and the usual value types."""
    rng = ctx.rng
    body = f"""; loremfile.dev sample configuration
; Comments use both ';' and '#'.

[server]
host = 127.0.0.1
port = 8080
workers = 4
debug = false
# a quoted value keeps its spaces
banner = "  {lorem.sentence(rng, 4, 6)}  "

[database]
url = postgresql://user:pass@localhost:5432/example
pool_size = 10
timeout_seconds = 30.5
ssl = true

[logging]
level = info
format = json
file = /var/log/loremfile/app.log

[features]
empty_value =
list = alpha, beta, gamma
unicode = café-naïve-Ω
"""
    return body.encode("utf-8")
