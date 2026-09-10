"""The weekly ops-log line (docs/09 §4).

One row a week on the unprotected `ops-log` branch, which is also the keep-alive commit
that stops GitHub disabling the scheduled workflows after 60 quiet days. It goes to that
branch rather than `main` because a ruleset bypass is granted by *actor*, not by path —
a bypass for the Actions app would have applied to every workflow, so the branch without
a ruleset is the smaller concession.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

HEADER = (
    "# ops-log\n\n"
    "One line a week, written by `health.yml` (docs/09 §4). This branch carries no\n"
    "ruleset; `main` keeps its pull-request requirement and no workflow is granted a\n"
    "bypass. The commit doubles as the keep-alive that stops GitHub disabling scheduled\n"
    "workflows after 60 quiet days.\n\n"
    "| week | R2 class A | R2 class B | missing-key GETs | notes |\n"
    "|---|---|---|---|---|\n"
)


def row(report: dict[str, object], *, today: dt.date | None = None) -> str:
    """One Markdown row from a `loremfile usage --json` document."""
    when = today or dt.datetime.now(tz=dt.UTC).date()
    summary = report.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}

    def number(*names: str) -> str:
        for name in names:
            if name in summary:
                return f"{int(summary[name]):,}"
        return "—"

    notes = "" if report.get("ok", True) else "check failed"
    return (
        f"| {when.isoformat()} "
        f"| {number('r2_class_a_mtd', 'r2_class_a_window')} "
        f"| {number('r2_class_b_mtd', 'r2_class_b_window')} "
        f"| {number('missing_key_reads')} "
        f"| {notes} |\n"
    )


def append(report_path: Path, log_path: Path, *, today: dt.date | None = None) -> str:
    """Append this week's row, creating the file with its header if absent.

    Idempotent for a given date: running twice in one day replaces the row rather than
    adding a second, so a re-run of the scheduled job does not double-count.
    """
    report = json.loads(report_path.read_text(encoding="utf-8"))
    line = row(report, today=today)
    existing = log_path.read_text(encoding="utf-8") if log_path.is_file() else HEADER

    stamp = line.split("|")[1].strip()
    kept = [
        row_line
        for row_line in existing.splitlines(keepends=True)
        if not (row_line.startswith("| ") and row_line.split("|")[1].strip() == stamp)
    ]
    log_path.write_text("".join(kept) + line, encoding="utf-8")
    return line


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415 - only the module entry point needs it

    parser = argparse.ArgumentParser(prog="loremfile.ops_log")
    parser.add_argument("--from", dest="report", required=True, type=Path)
    parser.add_argument("--append", dest="log", required=True, type=Path)
    args = parser.parse_args(argv)
    print(append(args.report, args.log).rstrip())  # noqa: T201 - a CLI entry point
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
