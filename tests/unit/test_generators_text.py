"""M3.1 text formats: generators, validator, negative tests, determinism tests."""

from __future__ import annotations

import configparser
import json
import tempfile
from pathlib import Path

import pytest

from loremfile.build import load_generators
from loremfile.catalog import Catalog, Fixture
from loremfile.generators import text
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import validate
from loremfile.validators.text import detect_bom, measure_line_endings

WORKDIR = Path(tempfile.gettempdir())
CATALOG = Catalog.load()


def ctx(path: str) -> GeneratorContext:
    return GeneratorContext(path=path, workdir=WORKDIR)


def fixture(path: str) -> Fixture:
    return CATALOG.by_path[path]


def check(path: str, data: bytes) -> None:
    """Full validation of one fixture, with the mime the catalog resolves for it."""
    entry = fixture(path)
    report = validate(data, entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures


# --- exact sizing ----------------------------------------------------------


@pytest.mark.parametrize("size", [1000, 4096, 100_000])
def test_lorem_sized_hits_the_size_exactly(size: int) -> None:
    data = text.lorem_sized(ctx("txt/lorem-1kb.txt"), size=size)
    assert len(data) == size
    assert data.endswith(b"\n")


def test_lorem_sized_never_ends_mid_word() -> None:
    data = text.lorem_sized(ctx("txt/lorem-1kb.txt"), size=1000)
    tail = data.rstrip(b" \n")
    allowed = tuple(bytes([b]) for b in b"abcdefghijklmnopqrstuvwxyz.,")
    assert tail.endswith(allowed), f"ends mid-word: {tail[-20:]!r}"


def test_one_long_line_is_a_single_line_of_exact_size() -> None:
    data = text.one_long_line(ctx("txt/very-long-line-1mb.txt"), size=100_000)
    assert len(data) == 100_000
    assert data.count(b"\n") == 1
    assert data.endswith(b"\n")


# --- line endings ----------------------------------------------------------


@pytest.mark.parametrize(("ending", "marker"), [("lf", b"\n"), ("crlf", b"\r\n")])
def test_lines_use_the_requested_ending(ending: str, marker: bytes) -> None:
    data = text.lines(ctx("txt/lf.txt"), count=10, line_ending=ending)
    assert data.count(marker) == 10
    style, count = measure_line_endings(data)
    assert (style, count) == (ending, 10)


def test_mixed_line_endings_are_reported_as_mixed() -> None:
    data = text.lines(ctx("txt/lf.txt"), count=9, line_ending="mixed")
    assert measure_line_endings(data)[0] == "mixed"


def test_unknown_line_ending_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown line_ending"):
        text.lines(ctx("txt/lf.txt"), count=2, line_ending="nel")


def test_a_file_with_no_terminator_still_counts_its_last_line() -> None:
    assert measure_line_endings(b"one\ntwo") == ("lf", 2)


def test_a_file_with_no_newlines_at_all() -> None:
    assert measure_line_endings(b"single") == ("none", 1)
    assert measure_line_endings(b"") == ("none", 0)


# --- encodings -------------------------------------------------------------


@pytest.mark.parametrize(
    ("encoding", "bom_marker"),
    [("utf-8", b"\xef\xbb\xbf"), ("utf-16le", b"\xff\xfe")],
)
def test_bom_is_written_and_detected(encoding: str, bom_marker: bytes) -> None:
    data = text.encoded(ctx("txt/utf8-bom.txt"), encoding=encoding, bom=True)
    assert data.startswith(bom_marker)
    assert detect_bom(data)[0] is True


def test_no_bom_by_default() -> None:
    data = text.encoded(ctx("txt/latin1.txt"), encoding="iso-8859-1")
    assert detect_bom(data)[0] is False


@pytest.mark.parametrize(
    ("encoding", "script"),
    [("iso-8859-1", None), ("windows-1252", None), ("shift_jis", "kanji"), ("gb2312", "hanzi")],
)
def test_encoded_output_really_decodes_in_its_charset(encoding: str, script: str | None) -> None:
    data = text.encoded(ctx("txt/x.txt"), encoding=encoding, script=script)
    data.decode(encoding, errors="strict")


def test_utf32le_bom_is_not_mistaken_for_utf16le() -> None:
    """The UTF-32LE BOM starts with the UTF-16LE BOM; order of checks matters."""
    assert detect_bom(b"\xff\xfe\x00\x00rest") == (True, "utf-32le")
    assert detect_bom(b"\xff\xfeA\x00") == (True, "utf-16le")


def test_multilingual_covers_the_scripts_it_promises() -> None:
    out = text.multilingual(ctx("txt/utf8-multilingual.txt")).decode("utf-8")
    for label in ("Latin", "Greek", "Cyrillic", "Arabic", "Hebrew", "Emoji"):
        assert label in out
    assert "\u200b" in out, "zero-width space"
    assert "\u00a0" in out, "non-breaking space"
    assert "\u202a" in out, "bidi control"


def test_emoji_only_is_only_emoji_and_whitespace() -> None:
    out = text.emoji_only(ctx("txt/emoji-only.txt"), count=20).decode("utf-8")
    assert out.strip()
    assert not any(c.isascii() and c.isalpha() for c in out)


# --- logs and ini ----------------------------------------------------------


def test_nginx_log_shape_and_documentation_ips() -> None:
    out = text.nginx_access_log(ctx("log/nginx-access-1000-lines.log"), count=50)
    body = out.decode()
    assert body.count("\n") == 50
    for line in body.splitlines():
        assert line.startswith("192.0.2."), "RFC 5737 documentation range only"
        assert '"' in line and "HTTP/1.1" in line


def test_json_lines_log_is_one_object_per_line() -> None:
    out = text.json_lines_log(ctx("log/json-lines-app-1000.log"), count=25).decode()
    records = [json.loads(line) for line in out.splitlines()]
    assert len(records) == 25
    assert {"ts", "level", "service", "trace_id", "msg", "duration_ms"} == set(records[0])
    assert records[0]["ts"].endswith("Z")


def test_ini_config_parses_with_the_standard_library() -> None:
    parser = configparser.ConfigParser(allow_no_value=True)
    parser.read_string(text.ini_config(ctx("ini/config.ini")).decode("utf-8"))
    assert parser["server"]["port"] == "8080"
    assert parser["database"]["pool_size"] == "10"
    assert parser["features"]["list"] == "alpha, beta, gamma"


# --- determinism -----------------------------------------------------------


@pytest.mark.parametrize(
    ("func", "kwargs", "path"),
    [
        (text.lorem_sized, {"size": 4096}, "txt/lorem-1kb.txt"),
        (text.lines, {"count": 20, "line_ending": "crlf"}, "txt/crlf.txt"),
        (text.encoded, {"encoding": "iso-8859-1"}, "txt/latin1.txt"),
        (text.multilingual, {}, "txt/utf8-multilingual.txt"),
        (text.emoji_only, {"count": 30}, "txt/emoji-only.txt"),
        (text.nginx_access_log, {"count": 20}, "log/nginx-access-1000-lines.log"),
        (text.json_lines_log, {"count": 20}, "log/json-lines-app-1000.log"),
        (text.ini_config, {}, "ini/config.ini"),
    ],
)
def test_running_twice_gives_identical_bytes(func, kwargs: dict, path: str) -> None:
    context = ctx(path)
    with deterministic(context.seed):
        first = func(context, **kwargs)
    with deterministic(context.seed):
        second = func(context, **kwargs)
    assert first == second


# --- negative tests --------------------------------------------------------


def test_validation_rejects_bytes_that_do_not_decode_in_the_declared_charset() -> None:
    entry = fixture("txt/shift-jis.txt")
    report = validate(b"\xff\xfe\x00 not shift-jis \xc3\x28", entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("decode" in failure for failure in report.failures)


def test_validation_rejects_a_bom_that_contradicts_the_declared_charset() -> None:
    entry = fixture("txt/latin1.txt")
    report = validate(b"\xef\xbb\xbfhello\n", entry, CATALOG.mime_for(entry))
    assert not report.ok


def test_validation_rejects_the_wrong_line_ending() -> None:
    entry = fixture("txt/lf.txt")
    data = text.lines(ctx("txt/lf.txt"), count=100, line_ending="crlf")
    report = validate(data, entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("line_ending" in failure for failure in report.failures)


def test_validation_rejects_the_wrong_line_count() -> None:
    entry = fixture("txt/lf.txt")
    data = text.lines(ctx("txt/lf.txt"), count=99, line_ending="lf")
    report = validate(data, entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("expect.lines" in failure for failure in report.failures)


# --- the real fixtures pass their own catalog entries ----------------------


@pytest.mark.parametrize(
    "path",
    [
        "txt/lf.txt",
        "txt/crlf.txt",
        "txt/utf8-multilingual.txt",
        "txt/emoji-only.txt",
        "ini/config.ini",
        "log/json-lines-app-1000.log",
    ],
)
def test_generated_fixture_satisfies_its_catalog_entry(path: str) -> None:
    entry = fixture(path)
    load_generators()
    context = ctx(path)
    with deterministic(context.seed):
        data = REGISTRY.get(entry.generator)(context, **entry.params)
    assert isinstance(data, bytes)
    check(path, data)
