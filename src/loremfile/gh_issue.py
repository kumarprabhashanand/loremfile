"""Open, update and close GitHub issues from a report (docs/09 §4).

De-duplicated by **label plus title**, so a failure that persists for a week is one
issue with seven comments rather than seven issues. It closes with a comment on the
first green run, which is the half that makes the label meaningful: an issue tracker
where nothing ever closes is one nobody reads.

Uses the `gh` CLI, which is in the toolchain image and already authenticated in Actions.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class IssueError(RuntimeError):
    """The gh CLI failed."""


@dataclass
class Outcome:
    action: str  # opened | commented | closed | unchanged
    number: int | None = None
    detail: str = ""


def _gh(args: list[str], *, check: bool = True) -> str:
    executable = shutil.which("gh")
    if executable is None:
        raise IssueError("gh is not on PATH; it lives in the toolchain image")
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [executable, *args], capture_output=True, text=True, timeout=120, check=False
    )
    if check and completed.returncode != 0:
        raise IssueError(f"gh {' '.join(args[:3])}…: {completed.stderr.strip()}")
    return completed.stdout


def find_open(label: str, title: str) -> int | None:
    """The open issue for this label and title, if any."""
    raw = _gh(["issue", "list", "--label", label, "--state", "open", "--json", "number,title"])
    for issue in json.loads(raw or "[]"):
        if issue["title"] == title:
            return int(issue["number"])
    return None


def summarise(report: Path) -> str:
    """The failing detail from a `--json` report, as a Markdown body."""
    document = json.loads(report.read_text(encoding="utf-8"))
    lines = [f"`{document.get('command', report.name)}` reported a failure.", ""]
    summary = document.get("summary") or {}
    if summary:
        lines += ["| metric | value |", "|---|---|"]
        lines += [f"| {key} | {value} |" for key, value in summary.items()]
        lines.append("")
    errors = document.get("errors") or []
    if errors:
        lines.append("```")
        lines += errors[:20]
        if len(errors) > 20:  # noqa: PLR2004 - a body nobody reads is not a report
            lines.append(f"… and {len(errors) - 20} more")
        lines.append("```")
    return "\n".join(lines)


def apply(*, label: str, title: str, report: Path, state: str) -> Outcome:
    """Reconcile the issue tracker with one report.

    `state` is `failing` or `ok`. The caller decides which, because the threshold that
    separates them belongs to the check, not to the issue plumbing.
    """
    existing = find_open(label, title)
    if state == "failing":
        body = summarise(report)
        if existing is None:
            url = _gh(
                ["issue", "create", "--label", label, "--title", title, "--body", body]
            ).strip()
            return Outcome("opened", detail=url)
        _gh(["issue", "comment", str(existing), "--body", body])
        return Outcome("commented", number=existing)

    if existing is None:
        return Outcome("unchanged", detail="green, and nothing was open")
    _gh(
        [
            "issue",
            "close",
            str(existing),
            "--comment",
            "Green on the latest run; closing. Reopened automatically if it recurs.",
        ]
    )
    return Outcome("closed", number=existing)


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415 - only the module entry point needs it

    parser = argparse.ArgumentParser(prog="loremfile.gh_issue")
    parser.add_argument("--label", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--state", required=True, choices=["failing", "ok"])
    args = parser.parse_args(argv)
    try:
        outcome = apply(label=args.label, title=args.title, report=args.report, state=args.state)
    except IssueError as exc:
        print(f"error: {exc}")  # noqa: T201 - this is a CLI entry point
        return 1
    print(f"{outcome.action} {outcome.number or ''} {outcome.detail}".strip())  # noqa: T201
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
