"""Archive fixtures — zip, tar and the single-stream compressors (docs/05 §3.8).

Every archive here is byte-stable, which takes more than sorting entries: each container
stores timestamps, permissions and ownership of its own, and several compressors record
the source's name and modification time in their header. Each generator below pins all of
them, and `util.zipnorm` does it for the zip-based formats.

The payloads are Lorem Ipsum or seeded noise, never a real file, so an archive can be
extracted anywhere without writing anything surprising to disk.
"""

from __future__ import annotations

import bz2
import gzip
import io
import lzma
import os
import tarfile
import zipfile
from pathlib import Path

import py7zr
import pyzipper
import zstandard

from loremfile.config import SOURCE_DATE_EPOCH
from loremfile.generators.base import GeneratorContext, generator
from loremfile.generators.text import lorem_sized
from loremfile.util import lorem
from loremfile.util.zipnorm import ZIP_EPOCH, normalize

#: tar stores an mtime, uid/gid and owner names per entry. All fixed, so two builds of the
#: same archive are identical and an extraction cannot produce a file owned by a real user.
TAR_MTIME = 0
TAR_OWNER = "loremfile"

#: gzip's header carries the source's name and mtime; both are dropped so the bytes of
#: `lorem-1mb.txt.gz` describe only its content.
GZIP_MTIME = 0
#: zlib's default, reproduced by every tool that writes gzip at "default compression".
GZIP_LEVEL = 6
#: zstd keeps a content checksum optional; off, so the frame depends only on the payload.
ZSTD_LEVEL = 10


def text_members(ctx: GeneratorContext, count: int, *, prefix: str = "") -> dict[str, bytes]:
    """`count` small Lorem Ipsum files, named predictably so tests can address them."""
    rng = ctx.rng
    return {
        f"{prefix}file-{index:03d}.txt": lorem.text(rng, 2).encode("utf-8")
        for index in range(1, count + 1)
    }


def nested_members(ctx: GeneratorContext) -> dict[str, bytes]:
    """A three-level directory tree, for extractors that must create directories."""
    rng = ctx.rng
    return {
        "readme.txt": lorem.text(rng, 1).encode("utf-8"),
        "docs/intro.txt": lorem.text(rng, 1).encode("utf-8"),
        "docs/deep/notes.txt": lorem.text(rng, 1).encode("utf-8"),
        "data/rows.csv": b"id,name\n1,alpha\n2,beta\n",
    }


def _zip_of(members: dict[str, bytes], *, comment: bytes = b"", stored: bool = False) -> bytes:
    """A zip of `members`, normalised: sorted, fixed stamps, fixed permissions."""
    out = io.BytesIO()
    method = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(out, "w", method) as archive:
        for name, body in sorted(members.items()):
            info = zipfile.ZipInfo(filename=name, date_time=ZIP_EPOCH)
            info.compress_type = method
            archive.writestr(info, body)
        if comment:
            archive.comment = comment
    data = out.getvalue()
    # `normalize` deflates everything, so a deliberately stored archive keeps its own bytes.
    return data if stored or comment else normalize(data)


@generator()
def zip_text_files(ctx: GeneratorContext, *, count: int = 3) -> bytes:
    """A zip of `count` Lorem Ipsum text files."""
    return _zip_of(text_members(ctx, count))


@generator()
def zip_nested(ctx: GeneratorContext) -> bytes:
    """A zip whose entries are in nested directories."""
    return _zip_of(nested_members(ctx))


@generator()
def zip_empty(_ctx: GeneratorContext) -> bytes:
    """The empty zip: a 22-byte end-of-central-directory record and nothing else."""
    return _zip_of({})


@generator()
def zip_stored(ctx: GeneratorContext) -> bytes:
    """A zip that stores its entries uncompressed, for readers that assume deflate."""
    return _zip_of(text_members(ctx, 3), stored=True)


@generator()
def zip_unicode_names(ctx: GeneratorContext) -> bytes:
    """Entry names outside ASCII, so the UTF-8 name flag (bit 11) has to be honoured."""
    rng = ctx.rng
    members = {
        "ascii.txt": lorem.text(rng, 1).encode("utf-8"),
        "grüße.txt": lorem.text(rng, 1).encode("utf-8"),
        "日本語.txt": lorem.text(rng, 1).encode("utf-8"),
        "эмодзи-🙂.txt": lorem.text(rng, 1).encode("utf-8"),
    }
    return _zip_of(members)


@generator()
def zip_empty_directories(ctx: GeneratorContext) -> bytes:
    """Directory entries with no files in them, which some extractors drop."""
    members = dict(text_members(ctx, 1))
    members["empty-one/"] = b""
    members["empty-two/nested/"] = b""
    return _zip_of(members)


@generator()
def zip_of_fixtures(ctx: GeneratorContext, *, paths: list[str]) -> bytes:
    """A zip of published fixtures, read through `ctx.dependency` and never regenerated."""
    return _zip_of({path.split("/", 1)[1]: ctx.dependency(path) for path in paths})


@generator()
def zip_with_comment(ctx: GeneratorContext) -> bytes:
    """A zip carrying an archive comment, which lives after the central directory."""
    return _zip_of(text_members(ctx, 3), comment=b"loremfile archive comment")


@generator()
def zip_zip64(_ctx: GeneratorContext, *, count: int = 70000) -> bytes:
    """Enough empty entries to force ZIP64: over 65,535 of them (the 16-bit count field)."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for index in range(count):
            info = zipfile.ZipInfo(filename=f"empty/{index:05d}.txt", date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, b"")
    return out.getvalue()


@generator(parallel_safe=False)
def zip_sized(ctx: GeneratorContext, *, size: int) -> Path:
    """About `size` bytes of incompressible payload in a zip, so the archive is honest."""
    target = _scratch(ctx, "sized.zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        info = zipfile.ZipInfo(filename="noise.bin", date_time=ZIP_EPOCH)
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, ctx.stream(size))
    return target


def _scratch(ctx: GeneratorContext, name: str) -> Path:
    """A workdir path unique to this fixture: tests share one workdir between generators."""
    return ctx.workdir / f"{ctx.path.replace('/', '-')}-{name}"


def _tar_of(
    members: dict[str, bytes],
    *,
    symlinks: dict[str, str] | None = None,
    tar_format: int = tarfile.PAX_FORMAT,
) -> bytes:
    """A tar with fixed stamps and ownership, entries sorted by name."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tar_format) as archive:
        for name, body in sorted(members.items()):
            info = tarfile.TarInfo(name=name)
            info.size = len(body)
            info.mtime = TAR_MTIME
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = TAR_OWNER
            archive.addfile(info, io.BytesIO(body))
        for name, target in sorted((symlinks or {}).items()):
            link = tarfile.TarInfo(name=name)
            link.type = tarfile.SYMTYPE
            link.linkname = target
            link.mtime = TAR_MTIME
            link.mode = 0o777
            link.uid = link.gid = 0
            link.uname = link.gname = TAR_OWNER
            archive.addfile(link)
    return out.getvalue()


@generator()
def tar_text_files(ctx: GeneratorContext, *, count: int = 3, compression: str = "") -> bytes:
    """`count` text files in a tar, optionally compressed as the catalog names it."""
    return compress(_tar_of(text_members(ctx, count)), compression)


@generator()
def tar_nested(ctx: GeneratorContext) -> bytes:
    """A tar whose entries are in nested directories."""
    return _tar_of(nested_members(ctx))


@generator()
def tar_symlinks(ctx: GeneratorContext) -> bytes:
    """Relative symlinks only: an extractor must not be able to escape the directory."""
    members = text_members(ctx, 2)
    links = {"latest.txt": "file-001.txt", "docs/copy.txt": "../file-002.txt"}
    return _tar_of(members, symlinks=links)


@generator()
def tar_long_names(ctx: GeneratorContext) -> bytes:
    """Names beyond the 100-byte ustar limit, stored as PAX headers."""
    rng = ctx.rng
    long_name = "/".join("very-long-directory-name-for-pax-headers" for _ in range(3))
    members = {
        f"{long_name}/{'x' * 120}.txt": lorem.text(rng, 1).encode("utf-8"),
        "short.txt": lorem.text(rng, 1).encode("utf-8"),
    }
    return _tar_of(members)


@generator(parallel_safe=False)
def tar_sized(ctx: GeneratorContext, *, size: int, compression: str = "gz") -> Path:
    """A compressed tar of about `size` bytes, from incompressible payload."""
    body = _tar_of({"noise.bin": ctx.stream(size)})
    target = _scratch(ctx, f"sized.tar.{compression}" if compression else "sized.tar")
    target.write_bytes(compress(body, compression))
    return target


def compress(data: bytes, kind: str) -> bytes:
    """One compressed stream, with every header field that could drift pinned."""
    if not kind:
        return data
    if kind == "gz":
        out = io.BytesIO()
        # `filename=""` and a fixed mtime: gzip otherwise records the source name and the
        # build time in its header, and the fixture's hash would change on every run.
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=out, compresslevel=GZIP_LEVEL, mtime=GZIP_MTIME
        ) as stream:
            stream.write(data)
        return out.getvalue()
    if kind == "bz2":
        return bz2.compress(data, compresslevel=9)
    if kind == "xz":
        return lzma.compress(data, format=lzma.FORMAT_XZ, preset=6)
    if kind == "zst":
        return zstandard.ZstdCompressor(level=ZSTD_LEVEL, write_checksum=False).compress(data)
    raise ValueError(f"unknown compression '{kind}'")


@generator(parallel_safe=False)
def compressed_text(ctx: GeneratorContext, *, size: int, kind: str) -> Path:
    """Lorem Ipsum of `size` bytes compressed on its own, the shape `gzip file` produces."""
    payload = lorem_sized(ctx, size=size)
    if not isinstance(payload, bytes):  # pragma: no cover - lorem_sized returns bytes
        raise TypeError("lorem_sized must return bytes")
    target = _scratch(ctx, f"payload.{kind}")
    target.write_bytes(compress(payload, kind))
    return target


@generator(parallel_safe=False)
def compressed_noise(ctx: GeneratorContext, *, size: int, kind: str) -> Path:
    """Incompressible bytes compressed on their own: the file barely shrinks, by design."""
    target = _scratch(ctx, f"noise.{kind}")
    target.write_bytes(compress(ctx.stream(size), kind))
    return target


@generator()
def gzip_multi_member(ctx: GeneratorContext, *, members: int = 3) -> bytes:
    """Concatenated gzip members: one file a reader must decompress to the end to read."""
    rng = ctx.rng
    return b"".join(
        compress(f"member {index}\n{lorem.text(rng, 1)}".encode(), "gz")
        for index in range(1, members + 1)
    )


@generator()
def zip_aes(
    ctx: GeneratorContext,
    *,
    password: str = "loremfile",  # noqa: S107 - published on purpose (docs/05 §3.8)
    count: int = 3,
) -> bytes:
    """An AES-256 encrypted zip. The password is published on purpose (docs/05 §3.8).

    The salt and IV come from `Cryptodome.Random`, not from `os.urandom`, so this archive
    is reproducible only because `util.determinism` patches that RNG too — spiked in M3.7
    after three builds produced three different files (docs/06 §4).
    """
    out = io.BytesIO()
    with pyzipper.AESZipFile(
        out, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
    ) as archive:
        archive.setpassword(password.encode("utf-8"))
        for name, body in sorted(text_members(ctx, count).items()):
            info = pyzipper.AESZipFile.zipinfo_cls(filename=name, date_time=ZIP_EPOCH)
            info.compress_type = pyzipper.ZIP_DEFLATED
            archive.writestr(info, body)
    return out.getvalue()


@generator(parallel_safe=False)
def sevenzip(ctx: GeneratorContext, *, count: int = 3, size: int = 0) -> Path:
    """A 7z archive of text files, or of `size` incompressible bytes.

    py7zr archives files from disk and stores each entry's mtime, so members are staged
    with the project epoch rather than whatever the filesystem reports.
    """
    staged = _scratch(ctx, "7z-input")
    staged.mkdir(parents=True, exist_ok=True)
    members = {"noise.bin": ctx.stream(size)} if size else text_members(ctx, count)
    target = _scratch(ctx, "out.7z")
    target.unlink(missing_ok=True)
    with py7zr.SevenZipFile(target, "w") as archive:
        for name, body in sorted(members.items()):
            source = staged / name
            source.write_bytes(body)
            os.utime(source, (SOURCE_DATE_EPOCH, SOURCE_DATE_EPOCH))
            archive.write(source, name)
    return target
