"""WebAssembly fixtures (docs/05 §3.12).

The module is assembled byte by byte rather than compiled: a toolchain would embed its own
version string and a build path, and the result would neither be reproducible nor small
enough to read. What comes out is a valid module exporting `add(i32, i32) -> i32`, which a
host can call to prove it really loaded and instantiated the file.
"""

from __future__ import annotations

from loremfile.generators.base import GeneratorContext, generator

MAGIC = b"\x00asm"
VERSION = (1).to_bytes(4, "little")

#: Section ids from the core specification.
TYPE_SECTION = 1
FUNCTION_SECTION = 3
EXPORT_SECTION = 7
CODE_SECTION = 10

#: Value and structure bytes: i32, a function type, and an exported function.
I32 = 0x7F
FUNC_TYPE = 0x60
EXPORT_FUNC = 0x00
#: Instructions: local.get, i32.add, end.
LOCAL_GET = 0x20
I32_ADD = 0x6A
END = 0x0B


def uleb128(value: int) -> bytes:
    """A WebAssembly unsigned integer: seven bits per byte, low group first."""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def vector(items: list[bytes]) -> bytes:
    """A vector: its length, then its elements."""
    return uleb128(len(items)) + b"".join(items)


def section(section_id: int, body: bytes) -> bytes:
    """A section: its id, its byte length, then its contents."""
    return bytes([section_id]) + uleb128(len(body)) + body


@generator()
def minimal_add(_ctx: GeneratorContext) -> bytes:
    """A module exporting `add(i32, i32) -> i32`, the smallest callable thing."""
    function_type = (
        bytes([FUNC_TYPE]) + vector([bytes([I32]), bytes([I32])]) + vector([bytes([I32])])
    )
    name = b"add"
    body = bytes([0])  # no local declarations
    body += bytes([LOCAL_GET, 0, LOCAL_GET, 1, I32_ADD, END])
    return (
        MAGIC
        + VERSION
        + section(TYPE_SECTION, vector([function_type]))
        + section(FUNCTION_SECTION, vector([bytes([0])]))
        + section(
            EXPORT_SECTION,
            vector([uleb128(len(name)) + name + bytes([EXPORT_FUNC, 0])]),
        )
        + section(CODE_SECTION, vector([uleb128(len(body)) + body]))
    )
