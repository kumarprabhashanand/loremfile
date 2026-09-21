"""Print the licence of every direct dependency, read from installed package metadata.

Regenerates the Python-libraries table in THIRD_PARTY.md. Run it inside the toolchain
image, where the dependencies are actually installed:

    docker run --rm -v "$PWD/tools:/t:ro" "$(cat tools/TOOLCHAIN_DIGEST)" \
        python /t/licences.py

Licences are read, never remembered: a package's own metadata is the source of truth.
"""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

REQUIREMENTS_IN = Path("/t/requirements.in")


def direct_dependencies(path: Path) -> list[str]:
    """Return the distribution names listed in a requirements.in, ignoring comments."""
    names = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if line:
            names.append(re.split(r"[<>=!\[]", line)[0].strip())
    return names


def licence_of(dist: metadata.Distribution) -> str:
    """Best available licence string: SPDX expression, then classifiers, then License."""
    md = dist.metadata
    expression = md.get("License-Expression")
    if expression:
        return expression
    classifiers = [c for c in (md.get_all("Classifier") or []) if c.startswith("License ::")]
    if classifiers:
        return "; ".join(c.split(":: ")[-1] for c in classifiers)
    legacy = md.get("License")
    return legacy.strip().splitlines()[0] if legacy else "UNKNOWN"


def main() -> int:
    for name in direct_dependencies(REQUIREMENTS_IN):
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            print(f"| `{name}` | ?? | NOT INSTALLED |")
            continue
        print(f"| `{dist.metadata['Name']}` | {dist.version} | {licence_of(dist)} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
