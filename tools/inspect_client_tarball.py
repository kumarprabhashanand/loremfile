#!/usr/bin/env python3
"""What must be true of the npm client's tarball *before* it is published (docs/09 §3.8).

The sibling of `inspect_client_wheel.py`, and for the same reason: npm does not allow
publishing a version twice, so a tarball that reaches it carrying the deploy tooling, an
install script or the wrong version cannot be replaced — only deprecated, and a deprecated
version is still installable by anyone who pins it.

1. every entry is a plain file under `package/`, and is `package.json`, the README, or
   something under `bin/` or `src/`;
2. no entry's path names a part of the repository's own tooling;
3. the packed `package.json` declares no dependency and no script, so installing it runs
   nothing and fetches nothing else;
4. the version inside the tarball is the version the tag asks for.
"""

from __future__ import annotations

import json
import sys
import tarfile
from pathlib import Path
from typing import Any

#: Parts of the repository that must never reach a published tarball. The same list as the
#: wheel's, named rather than counted.
FORBIDDEN = ("infra", "generators", "validators", "site", "upload", "release")
ROOT = "package/"
FILES = ("package/package.json", "package/README.md")
TREES = ("package/bin/", "package/src/")
#: Every field through which npm would install something else or run something.
INSTALLS = (
    "dependencies",
    "optionalDependencies",
    "peerDependencies",
    "bundleDependencies",
    "bundledDependencies",
    "scripts",
    "gypfile",
)


def _entries(members: list[tarfile.TarInfo]) -> list[str]:
    found: list[str] = []
    for member in members:
        name = member.name
        if not member.isfile():
            found.append(f"{name} is not a plain file")
        if not (name in FILES or name.startswith(TREES)):
            found.append(f"{name} is in the tarball and is not the client")
        lowered = name.lower()
        found += [
            f"{name} names the repository's {part} tooling"
            for part in FORBIDDEN
            if f"/{part}" in lowered
        ]
    return found


def _manifest(manifest: dict[str, Any], expected_version: str | None) -> list[str]:
    found = [
        f"package.json declares {field}, so installing it would do more"
        for field in INSTALLS
        if field in manifest
    ]
    if manifest.get("name") != "loremfile":
        found.append(f"the package is named {manifest.get('name')!r}, not 'loremfile'")
    if expected_version is not None and manifest.get("version") != expected_version:
        found.append(
            f"the tarball is version {manifest.get('version')!r}, "
            f"the tag asks for {expected_version!r}"
        )
    return found


def problems(tarball: Path, *, expected_version: str | None) -> list[str]:
    with tarfile.open(tarball, "r:gz") as archive:
        members = archive.getmembers()
        manifest: dict[str, Any] | None = None
        for member in members:
            if member.name == "package/package.json" and member.isfile():
                extracted = archive.extractfile(member)
                manifest = json.loads(extracted.read()) if extracted else None
    if not members:
        return [f"{tarball.name} holds nothing at all"]
    found = _entries(members)
    if manifest is None:
        return [*found, f"{tarball.name} has no package/package.json"]
    return found + _manifest(manifest, expected_version)


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:  # noqa: PLR2004 - the argument count
        print("usage: inspect_client_tarball.py <tarball> [expected-version]")
        return 2
    tarball = Path(argv[1])
    expected = argv[2] if len(argv) == 3 else None  # noqa: PLR2004
    found = problems(tarball, expected_version=expected)
    if found:
        print(f"{tarball.name} must not be published:")
        print("  " + "\n  ".join(found))
        return 1
    checked = "and its version" if expected else "(no version to check: not a tag build)"
    print(f"{tarball.name}: only the client, nothing run on install {checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
