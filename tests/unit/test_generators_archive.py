"""M3.7 archives: generators, validators, negative tests, determinism tests.

The property that matters here is byte stability. Every container in this group stores
something the machine knows and the fixture must not — a timestamp, an owner, a source
filename, a random salt — and each one is pinned by the generator. The determinism test
below builds each archive twice; the AES test also builds one *without* the guard, because
that archive is reproducible only while `util.determinism` patches the crypto RNG.
"""

from __future__ import annotations

import gzip
import io
import tarfile
import tempfile
import zipfile
from pathlib import Path

import pytest
import pyzipper

from loremfile.catalog import Catalog, Fixture
from loremfile.generators import archive as archive_generators
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import archive as archive_validators  # noqa: F401 - registers them
from loremfile.validators import validate

CATALOG = Catalog.load()
WORKDIR = Path(tempfile.gettempdir())
ARCHIVE_FORMATS = ("zip", "tar", "gz", "bz2", "xz", "zst", "7z")
#: Built in CI rather than here: tens of megabytes, twice, for no extra coverage.
SLOW = {"zip/10mb.zip", "zip/100mb.zip", "tar/10mb.tar.gz", "zip/zip64-70000-empty-files.zip"}


def fixture(path: str) -> Fixture:
    return CATALOG.by_path[path]


def build(path: str, *, guarded: bool = True) -> bytes:
    entry = fixture(path)
    ctx = GeneratorContext(path=path, workdir=WORKDIR)
    if not guarded:
        out = REGISTRY.get(entry.generator)(ctx, **entry.params)
        return out.read_bytes() if isinstance(out, Path) else out
    with deterministic(ctx.seed):
        out = REGISTRY.get(entry.generator)(ctx, **entry.params)
    return out.read_bytes() if isinstance(out, Path) else out


def check(path: str, payload: bytes | None = None) -> dict:
    entry = fixture(path)
    report = validate(
        payload if payload is not None else build(path), entry, CATALOG.mime_for(entry)
    )
    assert report.ok, report.failures
    return report.props


def refused(path: str, payload: bytes) -> str:
    """The failures a validator reports for bytes it must not accept.

    `validate` collects failures rather than raising, so a negative test asserts on the
    report: asserting on an exception would also pass for a validator that reported nothing.
    """
    entry = fixture(path)
    report = validate(payload, entry, CATALOG.mime_for(entry))
    assert not report.ok, f"{path} accepted bytes it should have refused"
    return " | ".join(report.failures)


def archive_fixtures() -> list[str]:
    return [f.path for f in CATALOG.fixtures() if f.format in ARCHIVE_FORMATS]


def buildable() -> list[str]:
    return [p for p in archive_fixtures() if p not in SLOW and not fixture(p).depends_on]


# --- the catalogue this file is about -------------------------------------


def test_every_archive_format_is_catalogued_and_generated() -> None:
    """Empty-set control: the parametrised tests below are vacuous without these."""
    assert {f.format for f in CATALOG.fixtures() if f.format in ARCHIVE_FORMATS} == set(
        ARCHIVE_FORMATS
    )
    assert len(buildable()) >= 25
    for path in archive_fixtures():
        assert REGISTRY.get(fixture(path).generator).func.__module__ == archive_generators.__name__


@pytest.mark.parametrize("path", buildable(), ids=lambda path: path)
def test_an_archive_is_byte_identical_on_a_second_build(path: str) -> None:
    assert build(path) == build(path)


@pytest.mark.parametrize("path", buildable(), ids=lambda path: path)
def test_an_archive_validates_against_its_catalog_entry(path: str) -> None:
    check(path)


# --- zip -------------------------------------------------------------------


def test_zip_entries_are_deflated_with_fixed_stamps_and_permissions() -> None:
    props = check("zip/3-text-files.zip")
    assert props["entries"] == 3
    assert props["method"] == "deflate"
    with zipfile.ZipFile(io.BytesIO(build("zip/3-text-files.zip"))) as archive:
        infos = archive.infolist()
    assert [info.filename for info in infos] == sorted(info.filename for info in infos)
    assert {info.date_time for info in infos} == {(1980, 1, 1, 0, 0, 0)}
    assert {info.external_attr >> 16 for info in infos} == {0o100644}


def test_the_stored_archive_really_stores() -> None:
    assert check("zip/stored-uncompressed.zip")["method"] == "store"


def test_the_empty_zip_is_the_22_byte_end_record() -> None:
    assert len(build("zip/empty.zip")) == 22
    assert check("zip/empty.zip")["entries"] == 0


def test_unicode_names_carry_the_utf8_flag() -> None:
    props = check("zip/unicode-filenames.zip")
    assert props["utf8_names"] is True
    with zipfile.ZipFile(io.BytesIO(build("zip/unicode-filenames.zip"))) as archive:
        assert any(not name.isascii() for name in archive.namelist())


def test_the_archive_comment_survives() -> None:
    assert check("zip/with-archive-comment.zip")["comment"] is True


def test_empty_directories_are_kept_as_entries() -> None:
    assert check("zip/with-empty-directories.zip")["directories"] == 2


# --- the AES archive, and why it is reproducible ---------------------------


def test_the_aes_archive_opens_with_its_published_password() -> None:
    data = build("zip/aes256-password-loremfile.zip")
    with pyzipper.AESZipFile(io.BytesIO(data)) as archive:
        archive.setpassword(b"loremfile")
        names = archive.namelist()
        body = archive.read(names[0])
    assert len(names) == 3
    assert body.strip(), "the entry decrypts to real content"
    assert check("zip/aes256-password-loremfile.zip")["encrypted"] is True


def test_the_aes_salt_comes_from_the_patched_crypto_rng() -> None:
    """The control for the M3.7 correction (docs/06 §4).

    pyzipper draws its salt from `Cryptodome.Random`, not `os.urandom`. Without the guard
    two builds differ, which is what the original claim missed; with it they are identical.
    """
    unguarded = {build("zip/aes256-password-loremfile.zip", guarded=False) for _ in range(2)}
    assert len(unguarded) == 2, "unguarded builds must differ, or this proves nothing"
    assert build("zip/aes256-password-loremfile.zip") == build("zip/aes256-password-loremfile.zip")


# --- tar -------------------------------------------------------------------


def test_tar_entries_carry_no_machine_identity() -> None:
    data = build("tar/3-text-files.tar")
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = archive.getmembers()
    assert {member.uid for member in members} == {0}
    assert {member.uname for member in members} == {"loremfile"}
    assert {member.mtime for member in members} == {0}


def test_symlinks_resolve_inside_the_archive() -> None:
    props = check("tar/with-symlinks.tar")
    assert props["symlinks"] == 2
    with tarfile.open(fileobj=io.BytesIO(build("tar/with-symlinks.tar"))) as archive:
        targets = [m.linkname for m in archive.getmembers() if m.issym()]
    assert targets and all(not target.startswith("/") for target in targets)


def test_long_names_use_pax_headers() -> None:
    props = check("tar/long-names-pax.tar")
    assert props["tar_format"] == "pax"
    assert props["max_name_bytes"] > 100, "the point is a name beyond the ustar limit"


@pytest.mark.parametrize("kind", ["gz", "bz2", "xz", "zst"])
def test_a_compressed_tar_reports_its_compression(kind: str) -> None:
    assert check(f"tar/3-text-files.tar.{kind}")["compression"] == kind


# --- the single-stream compressors -----------------------------------------


def test_the_gzip_header_carries_neither_name_nor_mtime() -> None:
    data = build("gz/lorem-1mb.txt.gz")
    assert data[3] & 0x08 == 0, "FNAME would embed the source filename"
    assert data[4:8] == b"\x00\x00\x00\x00", "a build-time mtime would move the hash"
    assert check("gz/lorem-1mb.txt.gz")["uncompressed_bytes"] == 1_000_000


def test_noise_barely_compresses_and_lorem_does() -> None:
    noise = check("gz/noise-1mb.bin.gz")["uncompressed_bytes"]
    assert noise == 1_000_000
    assert len(build("gz/noise-1mb.bin.gz")) > 0.99 * 1_000_000
    assert len(build("gz/lorem-1mb.txt.gz")) < 0.5 * 1_000_000


def test_the_multi_member_gzip_has_three_members() -> None:
    assert check("gz/multi-member-3.gz")["members"] == 3


def test_the_7z_archive_lists_its_entries() -> None:
    assert check("7z/3-text-files.7z")["entries"] == 3


# --- negative tests --------------------------------------------------------


def test_a_truncated_zip_fails_validation() -> None:
    data = build("zip/3-text-files.zip")
    assert "not a readable zip" in refused("zip/3-text-files.zip", data[: len(data) // 2])


def test_a_corrupt_entry_fails_its_crc() -> None:
    data = bytearray(build("zip/3-text-files.zip"))
    data[40] ^= 0xFF  # inside the first entry's compressed payload
    assert refused("zip/3-text-files.zip", bytes(data))


def test_a_gzip_that_names_its_source_is_refused() -> None:
    out = io.BytesIO()
    with gzip.GzipFile(filename="secret-path.txt", mode="wb", fileobj=out, mtime=0) as stream:
        stream.write(b"lorem")
    assert "original filename" in refused("gz/lorem-1mb.txt.gz", out.getvalue())


def test_a_gzip_with_a_build_time_mtime_is_refused() -> None:
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=1_700_000_000) as stream:
        stream.write(b"lorem")
    assert "non-zero mtime" in refused("gz/lorem-1mb.txt.gz", out.getvalue())


def test_a_symlink_that_escapes_the_archive_is_refused() -> None:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as archive:
        link = tarfile.TarInfo(name="escape.txt")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../etc/passwd"
        archive.addfile(link)
    assert "points outside the archive" in refused("tar/with-symlinks.tar", out.getvalue())


def test_a_decompression_bomb_is_refused_unless_declared() -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("zeros.bin", b"\x00" * 50_000_000)
    assert "above the" in refused("zip/3-text-files.zip", out.getvalue())
