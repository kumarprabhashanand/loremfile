"""Validators for the data formats (docs/04 §1.3).

Each reads the bytes back with an independent parser and reports the props the manifest
publishes. They build on `text_props` from the text validator, because every format here
is text and its encoding, BOM and line endings matter just as much as its structure.
"""

from __future__ import annotations

import csv as csv_module
import io
import json
import tomllib
from typing import Any

import yaml
from lxml import etree

from loremfile.catalog import Fixture
from loremfile.validators import ValidationError, register
from loremfile.validators.text import text_props

MAX_JSON_DEPTH_GUARD = 10_000


def _measure_depth(value: object) -> int:
    """How many **container** levels deep the structure goes.

    Scalars are not a level: ``{"a": 1}`` is depth 1, ``{"a": {"b": 1}}`` is 2, and a
    top-level string is 0. Counting the scalar leaf instead would make a file called
    `nested-100-levels.json` measure 101, which is the kind of off-by-one that ends up
    baked into a published manifest entry and can never be corrected.

    Iterative, because a 100-level fixture is exactly the sort of input that turns a
    recursive measure into a crash.
    """
    stack: list[tuple[object, int]] = [(value, 1)]
    deepest = 0
    while stack:
        node, level = stack.pop()
        if level > MAX_JSON_DEPTH_GUARD:
            raise ValidationError("nesting deeper than the guard; refusing to measure")
        if isinstance(node, dict):
            deepest = max(deepest, level)
            stack.extend((child, level + 1) for child in node.values())
        elif isinstance(node, list):
            deepest = max(deepest, level)
            stack.extend((child, level + 1) for child in node)
    return deepest


# --- csv and tsv -----------------------------------------------------------


def _delimited_props(data: bytes, mime: str, fixture: Fixture) -> dict[str, Any]:
    props = text_props(data, mime)
    charset = props["encoding"]
    text = data.decode(charset)
    if props["bom"]:
        text = text.lstrip("﻿")

    delimiter = "\t" if fixture.format == "tsv" else str(fixture.params.get("delimiter", ","))
    reader = csv_module.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    records = list(reader)
    if not records:
        raise ValidationError("no rows parsed")

    has_header = bool(fixture.params.get("header", True))
    body = records[1:] if has_header else records
    widths = {len(r) for r in records}
    if len(widths) != 1:
        raise ValidationError(f"ragged rows: differing column counts {sorted(widths)}")

    # A field needed quoting if it contains the delimiter, a quote or a line break.
    quoted = any(
        any(ch in cell for ch in (delimiter, '"', "\n", "\r")) for r in records for cell in r
    )
    props.update(
        {
            "rows": len(body),
            "columns": records[0] and len(records[0]),
            "delimiter": delimiter,
            "has_header": has_header,
            "quoted_fields": quoted,
        }
    )
    return props


@register("csv")
def validate_csv(data: bytes, fixture: Fixture, mime: str) -> dict[str, Any]:
    return _delimited_props(data, mime, fixture)


@register("tsv")
def validate_tsv(data: bytes, fixture: Fixture, mime: str) -> dict[str, Any]:
    return _delimited_props(data, mime, fixture)


# --- json and ndjson -------------------------------------------------------

TOP_TYPES = {
    dict: "object",
    list: "array",
    str: "string",
    int: "number",
    float: "number",
    bool: "boolean",
    type(None): "null",
}


@register("json")
def validate_json(data: bytes, _fixture: Fixture, mime: str) -> dict[str, Any]:
    props = text_props(data, mime)
    try:
        payload = json.loads(data.decode(props["encoding"]))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"is not valid JSON: {exc}") from exc
    props.update(
        {
            "top_type": TOP_TYPES.get(type(payload), "unknown"),
            "items": len(payload) if isinstance(payload, list | dict) else 0,
            "max_depth": _measure_depth(payload),
        }
    )
    return props


@register("ndjson")
def validate_ndjson(data: bytes, _fixture: Fixture, mime: str) -> dict[str, Any]:
    props = text_props(data, mime)
    text = data.decode(props["encoding"])
    lines = [line for line in text.split("\n") if line]
    depth = 0
    for number, line in enumerate(lines, 1):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"line {number} is not valid JSON: {exc}") from exc
        depth = max(depth, _measure_depth(payload))
    props.update({"top_type": "object", "items": len(lines), "max_depth": depth})
    return props


# --- xml -------------------------------------------------------------------


@register("xml")
def validate_xml(data: bytes, _fixture: Fixture, mime: str) -> dict[str, Any]:
    """Parse with entity resolution and network access off (docs/06 §6 step 2)."""
    props = text_props(data, mime)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        root = etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ValidationError(f"is not well-formed XML: {exc}") from exc
    tree = root.getroottree()
    namespaces = sorted({uri for uri in root.nsmap.values() if uri})
    props.update(
        {
            "root_element": etree.QName(root).localname,
            "has_dtd": tree.docinfo.internalDTD is not None,
            "namespaces": namespaces,
        }
    )
    return props


# --- yaml and toml ---------------------------------------------------------


@register("yaml")
def validate_yaml(data: bytes, _fixture: Fixture, mime: str) -> dict[str, Any]:
    props = text_props(data, mime)
    try:
        documents = list(yaml.safe_load_all(data.decode(props["encoding"])))
    except yaml.YAMLError as exc:
        raise ValidationError(f"is not valid YAML: {exc}") from exc
    first = documents[0] if documents else None
    props.update(
        {
            "documents": len(documents),
            "top_keys": sorted(first) if isinstance(first, dict) else [],
        }
    )
    return props


@register("toml")
def validate_toml(data: bytes, _fixture: Fixture, mime: str) -> dict[str, Any]:
    props = text_props(data, mime)
    try:
        payload = tomllib.loads(data.decode(props["encoding"]))
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(f"is not valid TOML: {exc}") from exc
    props.update({"documents": 1, "top_keys": sorted(payload)})
    return props
