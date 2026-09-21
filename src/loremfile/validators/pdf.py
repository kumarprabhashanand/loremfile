"""Validator for PDF fixtures (docs/04 §1.3, docs/06 §6).

Two independent readers, as docs/06 §6 requires: **pypdf** for structure and properties,
and **qpdf --check** for a stricter opinion on the file's internals. A PDF that pypdf
tolerates but qpdf rejects is exactly the kind of quietly malformed file that should
never be published.

The policy scan is separate and stricter still: `/JavaScript`, `/Launch` and
`/OpenAction` are forbidden outright (docs/13 §5).
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pypdf

from loremfile.catalog import Fixture
from loremfile.validators import ValidationError, register

#: The passwords for the encrypted fixture live in the catalog description, so the
#: validator has to be told which one to try. Keyed by the catalog's generator params.
# S105: this is the *name* of a catalog parameter, not a password. The actual
# passwords live in the catalog and in the fixture description, by design —
# an encrypted fixture nobody can open would be useless.
USER_PASSWORD_PARAM = "user_password"  # noqa: S105

#: A4 in points, for the props table.
A4_POINTS = (595.28, 841.89)


def _qpdf_check(data: bytes) -> str | None:
    """Run ``qpdf --check``. Returns an error string, or None when it is happy.

    Encrypted files need the password, so this is skipped for them — qpdf would refuse
    to open the file at all, which says nothing about whether it is well formed.
    """
    qpdf = shutil.which("qpdf")
    if qpdf is None:
        return None  # not in this environment; CI runs in the image where it is
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "check.pdf"
        path.write_bytes(data)
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [qpdf, "--check", str(path)], capture_output=True, timeout=120, check=False
        )
    if completed.returncode == 0:
        return None
    output = (completed.stdout + completed.stderr).decode("utf-8", "replace").strip()
    # qpdf exits 3 for warnings it recovered from; those still mean a malformed file.
    return output.splitlines()[-1] if output else f"qpdf exited {completed.returncode}"


@register("pdf")
def validate_pdf(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    password = fixture.params.get(USER_PASSWORD_PARAM)
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        encrypted = reader.is_encrypted
        if encrypted:
            if not password:
                raise ValidationError(
                    "is encrypted but the catalog entry declares no user_password"
                )
            if reader.decrypt(str(password)) == pypdf.PasswordType.NOT_DECRYPTED:
                raise ValidationError("the declared user_password does not open it")
        pages = len(reader.pages)
        if pages == 0:
            raise ValidationError("has no pages")
        first = reader.pages[0]
        width = round(float(first.mediabox.width), 2)
        height = round(float(first.mediabox.height), 2)
        has_images = any("/XObject" in (page.get("/Resources") or {}) for page in reader.pages)
        outline = bool(reader.outline)
        version = (data[:8].decode("ascii", "replace").strip() or "").removeprefix("%PDF-")
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"pypdf could not read it: {exc}") from exc

    if not encrypted:
        problem = _qpdf_check(data)
        if problem:
            raise ValidationError(f"qpdf --check rejected it: {problem}")

    return {
        "pages": pages,
        "page_width_pt": width,
        "page_height_pt": height,
        "encrypted": encrypted,
        "pdf_version": version,
        "has_outline": outline,
        "has_images": has_images,
    }
