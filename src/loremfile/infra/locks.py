"""Generate `infra/r2-locks.json` from the catalog (docs/08 §7b).

One indefinite lock rule per format prefix, plus `_locktest/`, which exists so M2.4 can
prove lock behaviour against a prefix that holds no fixture. Generated rather than
hand-maintained because a format added without its rule is a prefix a leaked T2 could
overwrite, and nobody would notice until it mattered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loremfile import config
from loremfile.catalog import Catalog

#: Written once by the M2.4 probe and never again; it proves the locks are real.
LOCKTEST_PREFIX = "_locktest/"


def locks_path() -> Path:
    return config.repo_root() / "infra" / "r2-locks.json"


def desired_rules(catalog: Catalog | None = None) -> list[dict[str, Any]]:
    loaded = catalog if catalog is not None else Catalog.load()
    formats = sorted({fixture.format for fixture in loaded.fixtures()})
    rules: list[dict[str, Any]] = [
        {
            "id": f"lock-{fmt}",
            "enabled": True,
            "prefix": f"{fmt}/",
            "condition": {"type": "Indefinite"},
        }
        for fmt in formats
    ]
    rules.append(
        {
            "id": "lock-locktest",
            "enabled": True,
            "prefix": LOCKTEST_PREFIX,
            "condition": {"type": "Indefinite"},
        }
    )
    return rules


def render(catalog: Catalog | None = None) -> str:
    return json.dumps({"rules": desired_rules(catalog)}, indent=2) + "\n"


def diff(catalog: Catalog | None = None) -> list[str]:
    """Prefixes the committed file is missing, or holds and should not."""
    target = locks_path()
    if not target.is_file():
        return ["infra/r2-locks.json does not exist; run `loremfile infra locks --write`"]
    committed = {rule["prefix"] for rule in json.loads(target.read_text())["rules"]}
    wanted = {rule["prefix"] for rule in desired_rules(catalog)}
    return [
        *(f"missing lock rule for {prefix}" for prefix in sorted(wanted - committed)),
        *(
            f"lock rule for {prefix} has no format in the catalog"
            for prefix in sorted(committed - wanted)
        ),
    ]
