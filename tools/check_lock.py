#!/usr/bin/env python3
"""Is `tools/requirements.lock` the faithful resolution of `tools/requirements.in`?

Two questions, both about the artifacts rather than about the diff (docs/09 §4):

1. **Is every constraint satisfied by what is pinned?** A floor nobody honoured is the
   failure the old rule was reaching for, and this asks it directly.
2. **Does regenerating reproduce the lock byte for byte?** Run `pip-compile` over a copy
   of the two files with the flags the header records, and compare.

**What the second check does not catch, measured rather than assumed.** pip-compile reuses
an existing entry *wholesale* — version and hashes — whenever the pin still satisfies the
constraints. Editing `click==8.5.0` to `click==8.4.0` by hand and regenerating therefore
reproduces the edited file exactly, and this check passes (tried on 2026-09-28, byte for
byte identical at 181,739 bytes). So it is not a tamper check. It catches a lock that no
longer resolves, one whose ordering, header or extras were rewritten, and a requirement
that disappeared from it — and the constraint check above catches a pin that violates a
floor. A *hash* that does not belong to its version is caught where it has to be anyway:
`pip install --require-hashes` at image build, which refuses the artifact.

What this replaces: "the lock must differ whenever requirements.in differs", which was a
statement about the diff and got the common case backwards. Dependabot raising a floor to
a version the lock already pins is a legitimate no-op — the resolution is unchanged, and
demanding a different lock for it can only be satisfied by making one up.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

#: Exactly the invocation recorded in the lock's own header, so the header it regenerates
#: is the header that is already committed.
PIP_COMPILE = (
    "pip-compile",
    "--allow-unsafe",
    "--generate-hashes",
    "--no-emit-index-url",
    "--strip-extras",
    "--output-file=tools/requirements.lock",
    "tools/requirements.in",
)


def pinned_versions(lock: str) -> dict[str, Version]:
    found: dict[str, Version] = {}
    for line in lock.splitlines():
        if line and not line[0].isspace() and not line.startswith(("#", "-")) and "==" in line:
            name, _, rest = line.partition("==")
            found[name.strip().lower().replace("_", "-")] = Version(rest.split()[0].strip(" \\"))
    return found


def unsatisfied(requirements: str, pinned: dict[str, Version]) -> list[str]:
    """Constraints in requirements.in that the lock does not meet."""
    problems = []
    for raw in requirements.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        version = pinned.get(requirement.name.lower().replace("_", "-"))
        if version is None:
            problems.append(f"{requirement.name} is in requirements.in and not in the lock")
        elif not requirement.specifier.contains(version, prereleases=True):
            problems.append(
                f"{requirement.name}{requirement.specifier} but the lock pins {version}"
            )
    return problems


def main(root: Path) -> int:
    requirements = (root / "tools" / "requirements.in").read_text(encoding="utf-8")
    committed = (root / "tools" / "requirements.lock").read_text(encoding="utf-8")

    problems = unsatisfied(requirements, pinned_versions(committed))
    if problems:
        print("check_lock: requirements.in asks for versions the lock does not pin:")
        print("  " + "\n  ".join(problems))
        return 1

    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        (work / "tools").mkdir()
        for name in ("requirements.in", "requirements.lock"):
            shutil.copy(root / "tools" / name, work / "tools" / name)
        result = subprocess.run(PIP_COMPILE, cwd=work, capture_output=True, text=True, check=False)  # noqa: S603
        if result.returncode != 0:
            print("check_lock: pip-compile could not resolve tools/requirements.in:")
            print(result.stderr.strip()[-2000:])
            return 1
        regenerated = (work / "tools" / "requirements.lock").read_text(encoding="utf-8")

    if regenerated != committed:
        print("check_lock: regenerating the lock does not reproduce it. Commit this instead:")
        print("  pip-compile " + " ".join(PIP_COMPILE[1:]))
        for line in _first_difference(committed, regenerated):
            print(line)
        return 1

    print(
        f"check_lock: {len(pinned_versions(committed))} pins, every requirements.in "
        "constraint satisfied, and the lock is a resolution pip-compile reproduces "
        "(which is not a tamper check — see this file's docstring)"
    )
    return 0


def _first_difference(committed: str, regenerated: str) -> list[str]:
    pairs = zip(committed.splitlines(), regenerated.splitlines(), strict=False)
    for number, (was, now) in enumerate(pairs, 1):
        if was != now:
            return [
                f"  first difference at line {number}:",
                f"    committed:   {was}",
                f"    regenerated: {now}",
            ]
    return [f"  the files differ in length: {len(committed)} vs {len(regenerated)} bytes"]


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".")))
