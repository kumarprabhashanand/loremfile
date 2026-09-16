"""Validators for the web formats (docs/06 §6).

Every fixture here is read back and then checked for the things that would make it unsafe
or unstable to publish: an event-handler attribute, a `javascript:` URL, a reference to a
host other than this one, or a timestamp taken from the machine. The markup is parsed by
html5lib and the XHTML by an XML parser, so "it parses" is an independent statement rather
than the generator's own opinion.
"""

from __future__ import annotations

import json
import re
from typing import Any

import html5lib
from html5lib.html5parser import ParseError
from lxml import etree

from loremfile.catalog import Fixture
from loremfile.validators import ValidationError, register

EVENT_HANDLER = re.compile(rb"\son[a-z]+\s*=", re.IGNORECASE)
JAVASCRIPT_URL = re.compile(rb"javascript\s*:", re.IGNORECASE)
URL = re.compile(rb"https?://([^/\"'\s>)]+)")
ALLOWED_HOSTS = {b"loremfile.dev", b"www.w3.org"}
#: Anything that would reach the network from a fixture.
NETWORK_CALLS = (b"fetch(", b"XMLHttpRequest", b"navigator.sendBeacon", b"import(")
#: `$` under re.M matches before the newline, and SubRip lines end CRLF — so the CR
#: has to be allowed for, or this pattern can never match a file the check above
#: demands be CRLF.
TIMECODE_SRT = re.compile(rb"^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}\r?$", re.M)
TIMECODE_VTT = re.compile(
    rb"^(?:[\w-]+\n)?\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}", re.M
)


def _inert(data: bytes, path: str) -> None:
    """The rules every published markup or script fixture obeys."""
    if EVENT_HANDLER.search(data):
        raise ValidationError(f"{path}: carries an event-handler attribute")
    if JAVASCRIPT_URL.search(data):
        raise ValidationError(f"{path}: carries a javascript: URL")
    hosts = set(URL.findall(data)) - ALLOWED_HOSTS
    if hosts:
        joined = ", ".join(sorted(host.decode("ascii", "replace") for host in hosts))
        raise ValidationError(f"{path}: refers to hosts other than this site: {joined}")
    for call in NETWORK_CALLS:
        if call in data:
            raise ValidationError(f"{path}: contains {call.decode()}, which reaches the network")


@register("html")
def validate_html(data: bytes, fixture: Fixture, mime: str) -> dict[str, Any]:
    _inert(data, fixture.path)
    text = data.decode("utf-8")
    if fixture.ext == "xhtml" or "xhtml" in mime:
        try:
            root = etree.fromstring(data)
        except etree.XMLSyntaxError as exc:
            raise ValidationError(f"is not well-formed XML: {exc}") from exc
        if b"<!ENTITY" in data:
            raise ValidationError("declares an entity, which an XHTML fixture must not")
        return {
            "markup": "xhtml",
            "root": etree.QName(root).localname,
            "namespace": etree.QName(root).namespace or "",
            "elements": len(list(root.iter())),
            "inline_script": "<script" in text,
        }
    try:
        document = html5lib.HTMLParser(strict=True, namespaceHTMLElements=False).parse(text)
    except ParseError as exc:
        raise ValidationError(f"does not parse as HTML5: {exc}") from exc
    if "<!doctype html>" not in text.lower():
        raise ValidationError("has no HTML5 doctype")
    if 'charset="utf-8"' not in text.lower().replace("charset=utf-8", 'charset="utf-8"'):
        raise ValidationError("declares no charset")
    return {
        "markup": "html",
        "elements": len(list(document.iter())),
        "lang": document.get("lang", ""),
        "dir": document.get("dir", ""),
        "inline_style": "<style" in text,
        "inline_script": "<script" in text,
        "tables": text.count("<table"),
    }


@register("css")
def validate_css(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    _inert(data, fixture.path)
    text = data.decode("utf-8")
    if text.count("{") != text.count("}"):
        raise ValidationError("has unbalanced braces, so it is not parsable CSS")
    if "@import" in text:
        raise ValidationError("uses @import, which fetches another stylesheet")
    return {
        "rules": text.count("{"),
        "at_rules": text.count("@"),
        "custom_properties": text.count("--"),
    }


@register("js")
def validate_js(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    _inert(data, fixture.path)
    text = data.decode("utf-8")
    if "eval(" in text or "Function(" in text:
        raise ValidationError("uses eval or the Function constructor")
    return {"lines": len(text.splitlines()), "logs": text.count("console.log")}


@register("webmanifest")
def validate_webmanifest(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    _inert(data, fixture.path)
    try:
        document = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"is not valid JSON: {exc}") from exc
    missing = [key for key in ("name", "start_url", "icons", "display") if key not in document]
    if missing:
        raise ValidationError(f"has no {', '.join(missing)}")
    return {
        "icons": len(document["icons"]),
        "display": document["display"],
        "keys": sorted(document),
    }


@register("srt")
def validate_srt(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    _inert(data, fixture.path)
    if b"\r\n" not in data:
        raise ValidationError("uses bare newlines; SubRip files are written with CRLF")
    cues = TIMECODE_SRT.findall(data)
    if not cues:
        raise ValidationError("has no cue with a SubRip timecode")
    numbers = [int(block.split(b"\r\n")[0]) for block in data.split(b"\r\n\r\n") if block.strip()]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValidationError("cue numbers are not consecutive from 1")
    return {"cues": len(cues), "encoding": "utf-8"}


@register("vtt")
def validate_vtt(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    _inert(data, fixture.path)
    if not data.startswith(b"WEBVTT"):
        raise ValidationError("does not start with the WEBVTT signature")
    cues = TIMECODE_VTT.findall(data)
    if not cues:
        raise ValidationError("has no cue with a WebVTT timecode")
    return {
        "cues": len(cues),
        "has_style": b"\nSTYLE" in data,
        "has_region": b"\nREGION" in data,
    }


@register("ipynb")
def validate_ipynb(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    _inert(data, fixture.path)
    try:
        document = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"is not valid JSON: {exc}") from exc
    if document.get("nbformat") != 4:  # noqa: PLR2004 - the only format this catalog ships
        raise ValidationError(f"is nbformat {document.get('nbformat')}, not 4")
    cells = document.get("cells") or []
    if not cells:
        raise ValidationError("has no cells")
    for cell in cells:
        for key in ("start_time", "end_time", "execution_time"):
            if key in json.dumps(cell.get("metadata", {})):
                raise ValidationError(f"a cell records {key}, which moves on every run")
    outputs = sum(len(cell.get("outputs", [])) for cell in cells)
    return {
        "cells": len(cells),
        "code_cells": sum(1 for cell in cells if cell["cell_type"] == "code"),
        "outputs": outputs,
    }


@register("har")
def validate_har(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    _inert(data, fixture.path)
    try:
        document = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"is not valid JSON: {exc}") from exc
    log = document.get("log")
    if not isinstance(log, dict) or "entries" not in log:
        raise ValidationError("has no log.entries, so it is not a HAR")
    starts = {entry["startedDateTime"] for entry in log["entries"]}
    if len(starts) != 1:
        raise ValidationError(f"entries carry {len(starts)} different start times, not one fixed")
    return {
        "entries": len(log["entries"]),
        "version": log.get("version", ""),
        "pages": len(log.get("pages", [])),
        "started": starts.pop(),
    }
