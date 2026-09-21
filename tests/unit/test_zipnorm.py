"""M1.7: zip normalisation makes zip-based fixtures reproducible (docs/06 §4)."""

from __future__ import annotations

import io
import zipfile

import pytest

from loremfile.util.zipnorm import (
    DEFLATE_LEVEL,
    EPUB_MIMETYPE,
    ZIP_EPOCH,
    entry_names,
    normalize,
)


def build(entries: list[tuple[str, str]], *, date_time: tuple[int, ...] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            info = zipfile.ZipInfo(name, date_time=date_time or (2024, 6, 1, 12, 30, 15))
            archive.writestr(info, content)
    return buffer.getvalue()


ENTRIES = [("b.txt", "beta"), ("a.txt", "alpha"), ("c/d.txt", "delta")]


def test_entry_order_does_not_affect_the_bytes() -> None:
    forwards = normalize(build(ENTRIES))
    backwards = normalize(build(list(reversed(ENTRIES))))
    assert forwards == backwards


def test_entries_come_out_sorted() -> None:
    assert entry_names(normalize(build(ENTRIES))) == ["a.txt", "b.txt", "c/d.txt"]


def test_timestamps_do_not_affect_the_bytes() -> None:
    early = normalize(build(ENTRIES, date_time=(1999, 1, 1, 0, 0, 0)))
    late = normalize(build(ENTRIES, date_time=(2030, 12, 31, 23, 59, 58)))
    assert early == late


def test_all_timestamps_are_the_zip_minimum() -> None:
    with zipfile.ZipFile(io.BytesIO(normalize(build(ENTRIES)))) as archive:
        assert {info.date_time for info in archive.infolist()} == {ZIP_EPOCH}


def test_normalisation_is_idempotent() -> None:
    once = normalize(build(ENTRIES))
    assert normalize(once) == once


def test_contents_survive_intact() -> None:
    with zipfile.ZipFile(io.BytesIO(normalize(build(ENTRIES)))) as archive:
        assert archive.read("a.txt") == b"alpha"
        assert archive.read("c/d.txt") == b"delta"
        assert archive.testzip() is None


def test_permissions_are_fixed() -> None:
    with zipfile.ZipFile(io.BytesIO(normalize(build(ENTRIES)))) as archive:
        assert {info.external_attr for info in archive.infolist()} == {(0o100644 & 0xFFFF) << 16}


def test_compression_is_deflate_at_the_default_level() -> None:
    assert DEFLATE_LEVEL == 6
    with zipfile.ZipFile(io.BytesIO(normalize(build(ENTRIES)))) as archive:
        assert {i.compress_type for i in archive.infolist()} == {zipfile.ZIP_DEFLATED}


def test_non_ascii_names_get_the_utf8_flag() -> None:
    data = normalize(build([("café/naïve.txt", "x")]))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info = archive.infolist()[0]
        assert info.flag_bits & 0x800, "bit 11 marks the name as UTF-8"
        assert info.filename == "café/naïve.txt"


# --- EPUB ------------------------------------------------------------------


def epub_bytes() -> bytes:
    return build(
        [
            ("META-INF/container.xml", "<container/>"),
            (EPUB_MIMETYPE, "application/epub+zip"),
            ("OEBPS/ch1.xhtml", "<html/>"),
        ]
    )


def test_epub_mimetype_is_first_and_stored() -> None:
    data = normalize(epub_bytes(), epub=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        assert infos[0].filename == EPUB_MIMETYPE
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert [i.filename for i in infos[1:]] == sorted(i.filename for i in infos[1:])


def test_epub_mode_still_normalises_deterministically() -> None:
    assert normalize(epub_bytes(), epub=True) == normalize(epub_bytes(), epub=True)


def test_epub_mode_without_a_mimetype_entry_fails_loudly() -> None:
    with pytest.raises(ValueError, match="no 'mimetype' entry"):
        normalize(build(ENTRIES), epub=True)


def test_plain_mode_does_not_special_case_mimetype() -> None:
    """Without epub=True the mimetype entry is just another sorted entry."""
    assert entry_names(normalize(epub_bytes()))[0] == "META-INF/container.xml"
