"""Normalise zip-based files so the same input always produces the same bytes.

docs/06 §4. Every zip-based format — docx, xlsx, pptx, epub, kmz and plain zip — goes
through :func:`normalize` before it is published. Without it, entry order and timestamps
vary between library versions and runs, and the fixture's sha256 would drift.

The one place the project's fixed 2020 epoch is *not* used: zip's DOS timestamp cannot
represent dates before 1980 and libraries disagree on how to round, so entries are
stamped 1980-01-01 00:00:00, the format minimum, which every implementation writes
identically.
"""

from __future__ import annotations

import io
import zipfile

#: The zip format's minimum timestamp. See the module docstring for why this, not 2020.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

#: Deflate level 6: the zlib default, and what every tool reproduces.
DEFLATE_LEVEL = 6

#: -rw-r--r-- for files, drwxr-xr-x for directories, in the high 16 bits.
FILE_ATTR = (0o100644 & 0xFFFF) << 16
DIR_ATTR = ((0o040755 & 0xFFFF) << 16) | 0x10

#: EPUB requires this entry first and stored uncompressed (OCF 3.0 §4.1).
EPUB_MIMETYPE = "mimetype"


def normalize(data: bytes, *, epub: bool = False) -> bytes:
    """Rewrite a zip archive canonically.

    Entries are sorted by name, timestamps fixed, permissions fixed, the UTF-8 name flag
    set where a name needs it, and everything deflated at level 6. ZIP64 is left to
    ``zipfile``, which turns it on only when the sizes actually require it.

    With ``epub=True`` the ``mimetype`` entry is written first and stored uncompressed,
    which the EPUB container format requires.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        names = sorted(source.namelist())
        if epub:
            if EPUB_MIMETYPE not in names:
                raise ValueError("epub=True but the archive has no 'mimetype' entry")
            names.remove(EPUB_MIMETYPE)
            names.insert(0, EPUB_MIMETYPE)
        payloads = {name: source.read(name) for name in names}
        directories = {name for name in names if name.endswith("/")}

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=DEFLATE_LEVEL) as target:
        for name in names:
            is_dir = name in directories
            info = zipfile.ZipInfo(filename=name, date_time=ZIP_EPOCH)
            info.compress_type = (
                zipfile.ZIP_STORED
                if (epub and name == EPUB_MIMETYPE) or is_dir
                else zipfile.ZIP_DEFLATED
            )
            info.external_attr = DIR_ATTR if is_dir else FILE_ATTR
            info.create_system = 3  # Unix, so external_attr means what we set
            # Bit 11 tells readers the name is UTF-8. zipfile sets it on write when the
            # name is non-ASCII, but setting it explicitly keeps the flag stable across
            # versions rather than depending on that behaviour.
            if not name.isascii():
                info.flag_bits |= 0x800
            target.writestr(info, payloads[name])
    return out.getvalue()


def entry_names(data: bytes) -> list[str]:
    """Entry names in stored order — useful for asserting normalisation in tests."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.namelist()
