"""The ops-log series (docs/09 §4).

One commit a week on the unprotected `ops-log` branch, which is also the keep-alive commit
that stops GitHub disabling the scheduled workflows after 60 quiet days. It goes to that
branch rather than `main` because a ruleset bypass is granted by *actor*, not by path —
a bypass for the Actions app would have applied to every workflow, so the branch without
a ruleset is the smaller concession.

**One commit a week, but one row a day.** The row carries `GetObject`/`userError` — the
missing-key rate — beside the Class B total, and each weekly commit backfills every day in
the report, so the resolution is daily even though the commits are weekly. That matters
because the number is only interesting as a *series*: before the site has an audience the
missing-key rate is uncontaminated background scanning, and it is the only baseline against
which post-launch traffic can be read. Cloudflare keeps 90 days of it (`usage.RETENTION_DAYS`)
and nothing keeps it after that, so the series is committed rather than re-queried.
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
    "One row per **day**, written weekly: each run backfills the days in its report, so\n"
    "the series survives the API's 90-day retention window. Counts are per day, not\n"
    "month-to-date, because a cumulative counter cannot express a rate.\n\n"
    "| date | R2 class A | R2 class B | missing-key GETs | notes |\n"
    "|---|---|---|---|---|\n"
)


def _cell(value: object) -> str:
    """A number, or an em dash — never `0` for an absent reading."""
    return f"{int(value):,}" if isinstance(value, int) else "—"


def _line(date: str, class_a: object, class_b: object, missing: object, notes: str) -> str:
    return f"| {date} | {_cell(class_a)} | {_cell(class_b)} | {_cell(missing)} | {notes} |\n"


def rows(report: dict[str, object], *, today: dt.date | None = None) -> list[str]:
    """Markdown rows from a `loremfile usage --json` document, oldest first.

    One row per day in the report's `daily` series. When the series is missing — an older
    report, or a failed read — a single row for `today` is written with em dashes, because
    a day with no numbers must not render as a day with zero traffic.
    """
    when = today or dt.datetime.now(tz=dt.UTC).date()
    notes = "" if report.get("ok", True) else "check failed"
    series = report.get("daily")
    if not isinstance(series, list) or not series:
        return [_line(when.isoformat(), None, None, None, notes or "no daily series")]
    out: list[str] = []
    for day in sorted(series, key=lambda d: str(d.get("date", ""))):
        if not isinstance(day, dict):
            continue
        out.append(
            _line(
                str(day.get("date", "")),
                day.get("r2_class_a"),
                day.get("r2_class_b"),
                day.get("missing_key_reads"),
                notes,
            )
        )
    return out


def _stamp_of(line: str) -> str:
    return line.split("|")[1].strip()


def append(report_path: Path, log_path: Path, *, today: dt.date | None = None) -> str:
    """Merge the report's rows into the log, creating it with its header if absent.

    Idempotent per date: a date already in the log is **replaced**, not added again, so a
    re-run of the scheduled job does not double-count and overlapping backfill windows
    converge on one row per day. Rows are kept in date order.
    """
    report = json.loads(report_path.read_text(encoding="utf-8"))
    lines = rows(report, today=today)
    existing = log_path.read_text(encoding="utf-8") if log_path.is_file() else HEADER

    incoming = {_stamp_of(line): line for line in lines}
    header: list[str] = []
    kept: dict[str, str] = {}
    for line in existing.splitlines(keepends=True):
        if line.startswith("| ") and _stamp_of(line) not in {"date", "week"}:
            kept.setdefault(_stamp_of(line), line)
        else:
            header.append(line)
    kept.update(incoming)
    ordered = [kept[stamp] for stamp in sorted(kept)]
    log_path.write_text("".join(header) + "".join(ordered), encoding="utf-8")
    return "".join(lines)


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
