"""Release archives (docs/09 §3.5).

**The bytes come from production, not from a rebuild.** That is the point of the
archive: it is the restore path when the bucket is gone, so an archive assembled from
regenerated fixtures would only prove the generators still run. It has to hold the bytes
that were actually served — which is also why every member is verified against the
manifest hash before it goes in.

Archives split at 1.5 GB into numbered parts with a `parts.txt` listing each part and
its SHA-256, so every asset stays under GitHub's 2 GB limit.

**Not exercisable until M5.5.** Nothing is published yet, so `fetch_published` has never
fetched a real object. The unit tests below drive it against a fake; a green suite here
is *not* end-to-end verification, and the first real run is the restore drill after M5.1
puts bytes in R2.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: GitHub refuses an asset above 2 GB; split well below it.
PART_LIMIT_BYTES = 1_500_000_000


class ReleaseError(RuntimeError):
    """An archive could not be assembled, or a member failed verification."""


@dataclass
class Archive:
    parts: list[Path] = field(default_factory=list)
    members: int = 0
    total_bytes: int = 0
    #: sha256 of each part, for parts.txt.
    digests: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        lines = [f"  {self.members} member(s), {self.total_bytes:,} bytes"]
        lines += [f"    {path.name}  {self.digests[path.name][:16]}…" for path in self.parts]
        return "\n".join(lines)


def added_since(
    current: list[dict[str, Any]], previous: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Entries in `current` that the previous release did not have.

    Compared by path only. An entry cannot change its bytes at a published path, so a
    path present in both is byte-identical in both, and shipping it again would only make
    the delta archive larger.
    """
    seen = {entry["path"] for entry in previous}
    return [entry for entry in current if entry["path"] not in seen]


def verify_member(entry: dict[str, Any], data: bytes) -> None:
    """Refuse anything that does not match the manifest. The archive is a restore path."""
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry["sha256"]:
        raise ReleaseError(
            f"{entry['path']}: fetched bytes hash {digest[:12]} but the manifest says "
            f"{entry['sha256'][:12]}. An archive of unverified bytes is not a restore path."
        )
    if len(data) != int(entry["bytes"]):
        raise ReleaseError(f"{entry['path']}: {len(data)} bytes, manifest says {entry['bytes']}")


def build_archive(
    entries: list[dict[str, Any]],
    fetch: Callable[[str], bytes],
    out_dir: Path,
    *,
    stem: str,
    part_limit: int = PART_LIMIT_BYTES,
) -> Archive:
    """Assemble the tar parts. `fetch` returns the **published** bytes for a path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = Archive()
    part_number = 1
    current: tarfile.TarFile | None = None
    current_path: Path | None = None
    current_bytes = 0

    def close() -> None:
        nonlocal current, current_path
        if current is not None and current_path is not None:
            current.close()
            archive.parts.append(current_path)
            archive.digests[current_path.name] = hashlib.sha256(
                current_path.read_bytes()
            ).hexdigest()
            current = None
            current_path = None

    for entry in entries:
        data = fetch(entry["path"])
        verify_member(entry, data)
        if current is None or current_bytes + len(data) > part_limit:
            close()
            current_path = out_dir / f"{stem}.part{part_number}.tar"
            # Not a context manager: a part stays open across loop iterations until it
            # fills, and close() below is the single place every part is finalised.
            current = tarfile.open(current_path, "w")  # noqa: SIM115
            current_bytes = 0
            part_number += 1
        info = tarfile.TarInfo(name=entry["path"])
        info.size = len(data)
        # Fixed metadata: an archive of the same fixtures is the same archive.
        info.mtime = 0
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        current.addfile(info, io.BytesIO(data))
        current_bytes += len(data)
        archive.members += 1
        archive.total_bytes += len(data)
    close()

    if archive.parts:
        listing = "\n".join(f"{archive.digests[path.name]}  {path.name}" for path in archive.parts)
        (out_dir / "parts.txt").write_text(listing + "\n", encoding="utf-8")
    return archive
