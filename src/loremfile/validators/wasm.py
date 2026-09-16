"""Validator for WebAssembly modules (docs/06 §6).

The module is parsed section by section rather than instantiated: the toolchain image
carries no WebAssembly runtime, and a structural read proves what the fixture claims —
that it is a valid module exporting a function of the declared signature.
"""

from __future__ import annotations

import io
from typing import Any

from loremfile.catalog import Fixture
from loremfile.generators.wasm import (
    CODE_SECTION,
    END,
    EXPORT_FUNC,
    EXPORT_SECTION,
    FUNCTION_SECTION,
    I32,
    MAGIC,
    TYPE_SECTION,
    VERSION,
)
from loremfile.validators import ValidationError, register


def _uleb128(stream: io.BytesIO) -> int:
    value, shift = 0, 0
    while True:
        chunk = stream.read(1)
        if not chunk:
            raise ValidationError("ends in the middle of an integer")
        value |= (chunk[0] & 0x7F) << shift
        if not chunk[0] & 0x80:
            return value
        shift += 7


def _sections(data: bytes) -> dict[int, bytes]:
    stream = io.BytesIO(data[8:])
    found: dict[int, bytes] = {}
    while True:
        head = stream.read(1)
        if not head:
            return found
        size = _uleb128(stream)
        body = stream.read(size)
        if len(body) != size:
            raise ValidationError(f"section {head[0]} claims {size} bytes and has {len(body)}")
        found[head[0]] = body


@register("wasm")
def validate_wasm(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
    if not data.startswith(MAGIC + VERSION):
        raise ValidationError(f"does not start with the wasm preamble: {data[:8].hex()}")
    sections = _sections(data)
    for required, name in (
        (TYPE_SECTION, "type"),
        (FUNCTION_SECTION, "function"),
        (EXPORT_SECTION, "export"),
        (CODE_SECTION, "code"),
    ):
        if required not in sections:
            raise ValidationError(f"has no {name} section, so it declares nothing callable")

    exports = io.BytesIO(sections[EXPORT_SECTION])
    names = []
    for _ in range(_uleb128(exports)):
        length = _uleb128(exports)
        name = exports.read(length).decode("utf-8")
        kind = exports.read(1)
        _uleb128(exports)  # the index this export refers to
        if kind[0] == EXPORT_FUNC:
            names.append(name)

    types = io.BytesIO(sections[TYPE_SECTION])
    count = _uleb128(types)
    types.read(1)  # the function-type tag
    params = [types.read(1)[0] for _ in range(_uleb128(types))]
    results = [types.read(1)[0] for _ in range(_uleb128(types))]
    if sections[CODE_SECTION][-1] != END:
        raise ValidationError("the last function body does not end with the `end` opcode")

    return {
        "exports": sorted(names),
        "types": count,
        "params": ["i32" if value == I32 else hex(value) for value in params],
        "results": ["i32" if value == I32 else hex(value) for value in results],
        "sections": sorted(sections),
    }
