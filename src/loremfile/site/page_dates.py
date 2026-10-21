"""When each page's content last changed: `page-dates.json` (docs/04 §7).

The sitemap's `lastmod` and a page's `dateModified` come from here rather than from the
build's date, so a deploy that changes no page's content moves no date. Each entry holds a
date and the sha256 of the page as rendered *without any date*: hashed with its date, a page
would change whenever its date did, and the date would move on every build.

Like `manifest.json`, the file is written by a command and committed, never edited by hand:
`loremfile site build --update-dates`. Without that flag, `site build` refuses a stale record.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

FILE: Final = "page-dates.json"
#: How many stale pages an error names before it counts the rest.
SHOWN: Final = 10


@dataclass(frozen=True)
class Entry:
    date: dt.date
    sha256: str


Record = dict[str, Entry]


def load(path: Path) -> Record:
    """The committed record. None yet is an empty one: every page starts at the build's date."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            key: Entry(dt.date.fromisoformat(value["date"]), value["sha256"])
            for key, value in data.items()
        }
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError(f"{path.name}: not a page-dates record ({exc})") from exc


def render(record: Record) -> bytes:
    data = {
        key: {"date": entry.date.isoformat(), "sha256": entry.sha256}
        for key, entry in sorted(record.items())
    }
    return (json.dumps(data, indent=2) + "\n").encode()


def update(previous: Record, hashes: dict[str, str], today: dt.date) -> Record:
    """A page keeps its date while its undated hash is unchanged, and otherwise moves to
    `today`, never backwards. A page no longer built drops out."""
    record: Record = {}
    for key, digest in sorted(hashes.items()):
        old = previous.get(key)
        if old is not None and old.sha256 == digest:
            record[key] = old
        else:
            record[key] = Entry(today if old is None else max(today, old.date), digest)
    return record


def stale(previous: Record, record: Record) -> list[str]:
    """The keys an update adds, changes or drops: empty when the committed record is current."""
    return sorted(
        key for key in previous.keys() | record.keys() if previous.get(key) != record.get(key)
    )


def settle(record: Record, changed: list[str], path: Path, *, write: bool) -> list[str]:
    """Write the record if asked; otherwise a stale one is an error naming the pages."""
    if not changed:
        return []
    if write:
        path.write_bytes(render(record))
        return []
    more = len(changed) - SHOWN
    shown = ", ".join(changed[:SHOWN]) + (f" and {more} more" if more > 0 else "")
    return [
        f"{FILE} is out of date for {len(changed)} page(s): {shown}. Run "
        f"`loremfile site build --update-dates` and commit {FILE} (docs/04 §7)."
    ]
