"""M3.7 WebAssembly: a module assembled byte by byte, and what makes it valid.

The module is not compiled, so there is no toolchain version or build path in it and the
bytes are the same everywhere. These tests read it back the way the validator does —
section by section — and then break each structural rule in turn, so the refusals are
demonstrated rather than assumed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from loremfile.catalog import Catalog, Fixture
from loremfile.generators import wasm as wasm_generators
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import validate
from loremfile.validators import wasm as wasm_validators  # noqa: F401 - registers it

CATALOG = Catalog.load()
WORKDIR = Path(tempfile.gettempdir())
PATH = "wasm/minimal-add.wasm"


def fixture(path: str = PATH) -> Fixture:
    return CATALOG.by_path[path]


def build(path: str = PATH) -> bytes:
    entry = fixture(path)
    ctx = GeneratorContext(path=path, workdir=WORKDIR)
    with deterministic(ctx.seed):
        out = REGISTRY.get(entry.generator)(ctx, **entry.params)
    assert isinstance(out, bytes)
    return out


def check(payload: bytes | None = None) -> dict:
    entry = fixture()
    report = validate(payload if payload is not None else build(), entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures
    return report.props


def refused(payload: bytes) -> str:
    entry = fixture()
    report = validate(payload, entry, CATALOG.mime_for(entry))
    assert not report.ok, "the validator accepted a module it should refuse"
    return " | ".join(report.failures)


def test_the_module_is_catalogued() -> None:
    """Empty-set control: every assertion below reads this row."""
    assert PATH in CATALOG.by_path


def test_the_module_is_byte_identical_on_a_second_build() -> None:
    assert build() == build()


def test_the_module_validates_against_its_catalog_entry() -> None:
    props = check()
    assert props["exports"] == ["add"]
    assert props["params"] == ["i32", "i32"]
    assert props["results"] == ["i32"]


def test_it_starts_with_the_wasm_preamble() -> None:
    data = build()
    assert data[:4] == wasm_generators.MAGIC
    assert data[4:8] == wasm_generators.VERSION


def test_it_carries_the_four_sections_a_callable_module_needs() -> None:
    assert check()["sections"] == [
        wasm_generators.TYPE_SECTION,
        wasm_generators.FUNCTION_SECTION,
        wasm_generators.EXPORT_SECTION,
        wasm_generators.CODE_SECTION,
    ]


def test_the_function_body_ends_with_the_end_opcode() -> None:
    assert build()[-1] == wasm_generators.END


def test_it_stays_small_enough_to_read_in_a_hex_dump() -> None:
    assert len(build()) < 100


def test_the_integer_encoding_is_little_endian_seven_bit_groups() -> None:
    """The one piece of arithmetic in the generator, checked against known values."""
    assert wasm_generators.uleb128(0) == b"\x00"
    assert wasm_generators.uleb128(7) == b"\x07"
    assert wasm_generators.uleb128(128) == b"\x80\x01"
    assert wasm_generators.uleb128(300) == b"\xac\x02"


# --- negative tests --------------------------------------------------------


def test_bytes_without_the_preamble_are_refused() -> None:
    assert "preamble" in refused(b"\x00asm\x09\x09\x09\x09" + build()[8:])


def test_a_truncated_module_is_refused() -> None:
    assert refused(build()[:20])


def test_a_module_without_an_export_section_is_refused() -> None:
    # Sections are walked rather than searched for: the export section's id, 0x07, also
    # occurs inside the type section's bytes, and slicing there corrupts the wrong one.
    data = build()
    kept, offset = data[:8], 8
    while offset < len(data):
        section_id = data[offset]
        size = data[offset + 1]
        end = offset + 2 + size
        if section_id != wasm_generators.EXPORT_SECTION:
            kept += data[offset:end]
        offset = end
    assert "export section" in refused(kept)


def test_a_section_that_lies_about_its_length_is_refused() -> None:
    data = bytearray(build())
    data[9] = 0x7E  # the type section's declared size, far beyond what follows
    assert "claims" in refused(bytes(data))
