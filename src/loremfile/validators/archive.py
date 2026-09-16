"""Validators for the archive formats (docs/06 §6).

An archive is read back with an independent reader and described by what that reader
finds: how many entries, how they are stored, whether the container needed ZIP64, and how
far the payload expands. The last one is a safety check as much as a measurement — an
archive that expands a thousandfold is a decompression bomb unless the catalog says why.
"""

from __future__ import annotations

import bz2
import gzip
import io
import lzma
import posixpath
import tarfile
import zipfile
import zlib
from typing import Any

import py7zr
import zstandard

from loremfile.catalog import Fixture
from loremfile.validators import ValidationError, register
from loremfile.validators.policy import check_decompression_ratio

#: zip flag bit 0 marks an encrypted entry; bit 11 marks a UTF-8 entry name.
FLAG_ENCRYPTED = 0x1
FLAG_UTF8_NAME = 0x800
#: The 16-bit entry count in the end-of-central-directory record: more needs ZIP64.
ZIP64_ENTRY_LIMIT = 0xFFFF
TAR_FORMATS = {tarfile.USTAR_FORMAT: "ustar", tarfile.GNU_FORMAT: "gnu", tarfile.PAX_FORMAT: "pax"}


def _ratio_props(fixture: Fixture, compressed: int, uncompressed: int) -> dict[str, Any]:
    violations = check_decompression_ratio(
        fixture.path, compressed, uncompressed, exceptions=fixture.policy_exceptions
    )
    if violations:
        raise ValidationError("; ".join(violation.detail for violation in violations))
    return {"uncompressed_bytes": uncompressed}


@register("zip")
def validate_zip(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            bad = (
                archive.testzip() if not any(i.flag_bits & FLAG_ENCRYPTED for i in infos) else None
            )
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"is not a readable zip: {exc}") from exc
    if bad is not None:
        raise ValidationError(f"entry '{bad}' fails its CRC")
    directories = [info for info in infos if info.is_dir()]
    methods = sorted({info.compress_type for info in infos})
    uncompressed = sum(info.file_size for info in infos)
    props = {
        "entries": len(infos),
        "directories": len(directories),
        "method": {zipfile.ZIP_STORED: "store", zipfile.ZIP_DEFLATED: "deflate"}.get(
            methods[0] if methods else zipfile.ZIP_STORED, "other"
        ),
        "encrypted": any(info.flag_bits & FLAG_ENCRYPTED for info in infos),
        "zip64": len(infos) > ZIP64_ENTRY_LIMIT,
        "comment": bool(zipfile.ZipFile(io.BytesIO(data)).comment),
        "utf8_names": any(info.flag_bits & FLAG_UTF8_NAME for info in infos),
    }
    return props | _ratio_props(fixture, len(data), uncompressed)


@register("tar")
def validate_tar(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    kind = _stream_kind(data)
    # Decompressed here rather than by `tarfile`, whose "r:*" has no zstd mode in this
    # Python (docs/06 §9): a .tar.zst would be reported as an unreadable tar.
    body = _decompress(data, kind) if kind else data
    try:
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:") as archive:
            members = archive.getmembers()
            fmt = TAR_FORMATS.get(archive.format, "unknown")
    except tarfile.TarError as exc:
        raise ValidationError(f"is not a readable tar: {exc}") from exc
    symlinks = [member for member in members if member.issym()]
    for link in symlinks:
        target = link.linkname
        # Resolved against the link's own directory: `docs/copy.txt -> ../file.txt` stays
        # inside the archive, and only a target that climbs past the root escapes it.
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(link.name), target))
        if target.startswith("/") or resolved.startswith(".."):
            raise ValidationError(f"symlink '{link.name}' points outside the archive: {target}")
    props = {
        "entries": len(members),
        "directories": sum(member.isdir() for member in members),
        "symlinks": len(symlinks),
        "tar_format": fmt,
        "compression": kind,
        "max_name_bytes": max((len(member.name.encode()) for member in members), default=0),
        "mtimes": sorted({member.mtime for member in members}),
    }
    return props | _ratio_props(fixture, len(data), sum(member.size for member in members))


def _stream_kind(data: bytes) -> str:
    """Which compressor wrote this stream, by magic — '' for an uncompressed one."""
    for magic, kind in (
        (b"\x1f\x8b", "gz"),
        (b"BZh", "bz2"),
        (b"\xfd7zXZ\x00", "xz"),
        (b"\x28\xb5\x2f\xfd", "zst"),
    ):
        if data.startswith(magic):
            return kind
    return ""


def _decompress(data: bytes, kind: str) -> bytes:
    if kind == "gz":
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            return stream.read()
    if kind == "bz2":
        return bz2.decompress(data)
    if kind == "xz":
        return lzma.decompress(data)
    if kind == "zst":
        return zstandard.ZstdDecompressor().decompressobj().decompress(data)
    raise ValidationError(f"is not a compressed stream this validator knows: {kind or 'none'}")


def _stream_props(data: bytes, fixture: Fixture, expected: str) -> dict[str, Any]:
    kind = _stream_kind(data)
    if kind != expected:
        raise ValidationError(f"starts with {kind or 'no known'} magic, not {expected}")
    try:
        payload = _decompress(data, kind)
    except (OSError, lzma.LZMAError, zstandard.ZstdError, EOFError) as exc:
        raise ValidationError(f"does not decompress: {exc}") from exc
    props = {"compression": kind, "members": _gzip_members(data) if kind == "gz" else 1}
    return props | _ratio_props(fixture, len(data), len(payload))


def _gzip_members(data: bytes) -> int:
    """Concatenated gzip members, counted by decompressing one after another."""
    members, rest = 0, data
    while rest:
        decompressor = zlib.decompressobj(16 + 15)
        decompressor.decompress(rest)
        members += 1
        rest = decompressor.unused_data
    return members


@register("gz")
def validate_gz(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    props = _stream_props(data, fixture, "gz")
    # Byte 3 is the flag field: bit 3 (FNAME) would embed the source's name, and bytes
    # 4..8 its mtime. Both must be absent, or the fixture's hash depends on the build.
    if data[3] & 0x08:
        raise ValidationError("carries the original filename in its header")
    if data[4:8] != b"\x00\x00\x00\x00":
        raise ValidationError("carries a non-zero mtime in its header")
    return props


@register("bz2")
def validate_bz2(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    return _stream_props(data, fixture, "bz2")


@register("xz")
def validate_xz(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    return _stream_props(data, fixture, "xz")


@register("zst")
def validate_zst(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    return _stream_props(data, fixture, "zst")


@register("7z")
def validate_7z(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    try:
        with py7zr.SevenZipFile(io.BytesIO(data)) as archive:
            entries = archive.list()
            names = archive.getnames()
    except py7zr.Bad7zFile as exc:
        raise ValidationError(f"is not a readable 7z: {exc}") from exc
    uncompressed = sum(entry.uncompressed or 0 for entry in entries)
    props = {
        "entries": len(names),
        "directories": sum(1 for entry in entries if entry.is_directory),
        "encrypted": bool(archive.password_protected),
    }
    return props | _ratio_props(fixture, len(data), uncompressed)
