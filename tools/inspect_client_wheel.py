#!/usr/bin/env python3
"""What must be true of the client wheel *before* it is uploaded (docs/09 §3.7).

Three assertions, and the order they run in does not matter because any one of them
failing stops the upload:

1. every module in the wheel belongs to `loremfile_client`;
2. no member's path names a part of the repository's own tooling;
3. the version inside the wheel is the version the tag asks for.

**Before**, not after. PyPI does not allow re-uploading a version: a wheel published with
the deploy tooling in it, or under the wrong version, cannot be replaced — only yanked,
which leaves it downloadable by anyone who pins it. An inspection that runs after the
upload has nothing left to protect.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

#: Parts of the repository that must never reach a published wheel. Named rather than
#: counted: each one is a directory somebody could import into the client by accident.
FORBIDDEN = ("infra", "generators", "validators", "site", "upload", "release")
PACKAGE = "loremfile_client/"


def problems(wheel: Path, *, expected_version: str | None) -> list[str]:
    found: list[str] = []
    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()
        metadata = next((m for m in members if m.endswith(".dist-info/METADATA")), None)
        version_text = archive.read(metadata).decode() if metadata else ""

    modules = [name for name in members if name.endswith(".py")]
    if not modules:
        return [f"{wheel.name} holds no Python modules at all"]

    for name in modules:
        if not name.startswith(PACKAGE):
            found.append(f"{name} is in the wheel and is not part of {PACKAGE}")
    for name in members:
        lowered = name.lower()
        for part in FORBIDDEN:
            if lowered.startswith(part) or f"/{part}" in lowered:
                found.append(f"{name} names the repository's {part} tooling")

    if expected_version is not None:
        version = next(
            (
                line.split(": ", 1)[1].strip()
                for line in version_text.splitlines()
                if line.startswith("Version: ")
            ),
            "",
        )
        if version != expected_version:
            found.append(f"the wheel is version {version!r}, the tag asks for {expected_version!r}")
    return found


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:  # noqa: PLR2004 - the argument count
        print("usage: inspect_client_wheel.py <wheel> [expected-version]")
        return 2
    wheel = Path(argv[1])
    expected = argv[2] if len(argv) == 3 else None  # noqa: PLR2004
    found = problems(wheel, expected_version=expected)
    if found:
        print(f"{wheel.name} must not be published:")
        print("  " + "\n  ".join(found))
        return 1
    checked = "and its version" if expected else "(no version to check: not a tag build)"
    print(f"{wheel.name}: only {PACKAGE} modules, no repository tooling {checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
