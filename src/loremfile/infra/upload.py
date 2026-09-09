"""Publish fixtures and the site to R2 (docs/09 §5).

The plan is a pure function of (manifest, what is live, what bytes are available), so
every rule below is testable without a bucket. Two of them are gates that stop the
deploy rather than shaping it:

**No upload to an unlocked prefix.** Locks were deferred through M3 so that
pre-publication mistakes stayed correctable, and that argument expires at the first
deploy (`docs/08` §2). A first deploy onto an unlocked bucket leaves published fixtures
mutable by a leaked T2, which is the threat ADR-023 exists to close.

**Never rebuild an `expected_drift` path.** Those bytes do not reproduce on other
hardware (`docs/06` §4), so the manifest describes bytes that exist only in the
carry-forward artifact until they are published. A rebuild would produce *different*
bytes that fail the hash comparison — or, worse, be uploaded if the comparison were ever
relaxed. The deploy fails when the artifact is missing rather than substituting a
rebuild.

Nothing here overwrites a fixture. A live object whose hash differs from the manifest
fails the job: at that point either the manifest or the bucket is wrong, and guessing
which would be how a published byte changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from loremfile.catalog import Catalog

#: Multipart above this, per docs/09 §5.
MULTIPART_THRESHOLD = 16 * 1024 * 1024
MULTIPART_CHUNK = 16 * 1024 * 1024
MULTIPART_THREADS = 8


class Action(StrEnum):
    UPLOAD = "upload"
    SKIP = "skip"
    REMOVE = "remove"
    #: The job stops. Never "overwrite".
    FAIL = "fail"


@dataclass(frozen=True)
class Step:
    key: str
    action: Action
    reason: str = ""
    source: str = ""
    size: int = 0


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    #: Gate failures, which are not per-key and stop the whole plan.
    blockers: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers and not any(s.action is Action.FAIL for s in self.steps)

    def by_action(self, action: Action) -> list[Step]:
        return [s for s in self.steps if s.action is action]

    def render(self) -> str:
        counts = {a.value: len(self.by_action(a)) for a in Action}
        total = sum(s.size for s in self.by_action(Action.UPLOAD))
        lines = [f"  {k}={v}" for k, v in counts.items()]
        lines.append(f"  bytes={total:,}")
        for step in self.steps:
            if step.action in {Action.FAIL, Action.REMOVE}:
                lines.append(f"  {step.action.value:<7} {step.key}  {step.reason}")
        for blocker in self.blockers:
            lines.append(f"  BLOCKED {blocker}")
        return "\n".join(lines)


# --- gates ------------------------------------------------------------------


def prefix_of(key: str) -> str:
    """`pdf/a4-3pages.pdf` -> `pdf/`. Site keys have no prefix and are never locked."""
    head, slash, _ = key.partition("/")
    return f"{head}{slash}" if slash else ""


def unlocked_prefixes(keys: list[str], lock_rules: list[dict[str, Any]]) -> list[str]:
    """Prefixes a write would touch that no enabled lock rule covers.

    Checked against the rules the deploy can actually see. `docs/08` §6 notes that
    reading the *applied* rules needs an account-scoped R2 read, which the deploy's
    credentials do not have — so the caller passes the committed `infra/r2-locks.json`
    and the report says so. `audit.py` compares committed against applied separately;
    conflating them would let this gate claim a verification it never performed.
    """
    covered = {
        str(rule.get("prefix", "")) for rule in lock_rules if rule.get("enabled", False) is True
    }
    missing = sorted({prefix_of(key) for key in keys} - covered - {""})
    return missing


def carry_forward_gate(keys: list[str], catalog: Catalog, available: dict[str, Path]) -> list[str]:
    """Every `expected_drift` key being uploaded must have carried-forward bytes.

    Returns the blockers. The failure mode this prevents is silent: without it the deploy
    would rebuild the fixture, get different bytes on different hardware, and either fail
    the hash comparison for a confusing reason or — if that comparison were ever relaxed —
    publish bytes the manifest does not describe.
    """
    by_path = catalog.by_path
    blockers = []
    for key in keys:
        fixture = by_path.get(key)
        if fixture is None or not fixture.expected_drift:
            continue
        if key not in available:
            blockers.append(
                f"{key}: marked expected_drift and not present in the carry-forward "
                "artifact. These bytes cannot be rebuilt on other hardware (docs/06 §4), "
                "so the deploy must publish the artifact rather than regenerate. Refusing "
                "rather than substituting a rebuild."
            )
    return blockers


# --- the plan ---------------------------------------------------------------


def plan_fixtures(
    entries: list[dict[str, Any]],
    live: dict[str, str],
    available: dict[str, Path],
    *,
    catalog: Catalog,
    lock_rules: list[dict[str, Any]],
) -> Plan:
    """What `upload --fixtures` would do.

    ``live`` maps key -> the ``sha256`` metadata already in the bucket; ``available``
    maps key -> a file holding the bytes to upload.
    """
    plan = Plan()
    active = [e for e in entries if e.get("status", "active") == "active"]

    for entry in active:
        key = entry["path"]
        stored = live.get(key)
        if stored is not None:
            if stored == entry["sha256"]:
                plan.steps.append(Step(key, Action.SKIP, "already published, hash matches"))
            else:
                plan.steps.append(
                    Step(
                        key,
                        Action.FAIL,
                        f"live object hash {stored[:12]} != manifest {entry['sha256'][:12]}. "
                        "Published bytes never change (docs/03 §7.1); this is either a "
                        "wrong manifest or a wrong bucket and the deploy must not guess.",
                    )
                )
            continue
        source = available.get(key)
        if source is None:
            plan.steps.append(
                Step(key, Action.FAIL, "absent from the bucket and no bytes available to upload")
            )
            continue
        plan.steps.append(Step(key, Action.UPLOAD, source=str(source), size=int(entry["bytes"])))

    uploads = [s.key for s in plan.by_action(Action.UPLOAD)]
    plan.blockers += carry_forward_gate(uploads, catalog, available)
    unlocked = unlocked_prefixes(uploads, lock_rules)
    if unlocked:
        plan.blockers.append(
            f"no bucket lock rule covers {unlocked}. Publishing there would leave those "
            "objects overwritable by a leaked T2 (ADR-023). Add the rules with "
            "`loremfile infra locks --write` and have the owner apply them first."
        )
    return plan


def plan_removals(entries: list[dict[str, Any]], live: dict[str, str]) -> Plan:
    """`--apply-removals`: only tombstoned entries, and only ones still present.

    The only delete path in the tool besides `probe --down`. Anything else is refused by
    construction: this never sees a key that is not a tombstone in the manifest.
    """
    plan = Plan()
    for entry in entries:
        key = entry["path"]
        if entry.get("status") != "removed":
            continue
        if key in live:
            plan.steps.append(Step(key, Action.REMOVE, entry.get("reason", "tombstoned")))
    return plan


def plan_site(
    files: dict[str, tuple[Path, str]], live: dict[str, str], *, force: bool = False
) -> Plan:
    """`--site`: upload changed files. Site keys are mutable — they are not fixtures."""
    plan = Plan()
    for key, (source, digest) in sorted(files.items()):
        if not force and live.get(key) == digest:
            plan.steps.append(Step(key, Action.SKIP, "unchanged"))
            continue
        plan.steps.append(Step(key, Action.UPLOAD, source=str(source), size=source.stat().st_size))
    return plan
