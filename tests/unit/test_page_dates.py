"""page-dates.json: a page's date moves when its content does, and at no other time.

docs/04 §7. The trap this is built around: a page hashed *with* its date changes whenever its
date does, so the date would move on every build. Every rule here has a control beside it:
an unchanged page keeps its date *and* a changed one moves, the dated page really differs
between days *and* its hash does not, a stale record is refused *and* a current one is not.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from loremfile import cli
from loremfile.site import build, page_dates, routes

ROOT = Path(__file__).resolve().parents[2]
DAY1 = dt.datetime(2026, 11, 2, 9, 0, tzinfo=dt.UTC)
DAY2 = dt.datetime(2026, 11, 9, 9, 0, tzinfo=dt.UTC)
A, B = "a" * 64, "b" * 64


def entry(day: str, digest: str) -> page_dates.Entry:
    return page_dates.Entry(dt.date.fromisoformat(day), digest)


# --- the rules ---------------------------------------------------------------------------


def test_an_unchanged_hash_keeps_its_date_and_a_changed_one_moves() -> None:
    previous = {"pdf": entry("2026-10-01", A), "docs/faq": entry("2026-10-01", A)}
    record = page_dates.update(previous, {"pdf": A, "docs/faq": B}, DAY2.date())
    assert record["pdf"] == entry("2026-10-01", A)
    assert record["docs/faq"] == entry("2026-11-09", B)
    assert page_dates.stale(previous, record) == ["docs/faq"]


def test_a_date_never_moves_backwards() -> None:
    """A build whose commit is older than the record (a rebase, a skewed clock) keeps the
    later date; the control is a new page, which takes the build's date."""
    previous = {"pdf": entry("2026-12-01", A)}
    record = page_dates.update(previous, {"pdf": B, "new": A}, DAY1.date())
    assert record["pdf"] == entry("2026-12-01", B)
    assert record["new"] == entry("2026-11-02", A)


def test_a_page_no_longer_built_drops_out() -> None:
    previous = {"pdf": entry("2026-10-01", A), "gone": entry("2026-10-01", A)}
    record = page_dates.update(previous, {"pdf": A}, DAY1.date())
    assert set(record) == {"pdf"}
    assert page_dates.stale(previous, record) == ["gone"]


def test_the_record_round_trips_sorted_with_a_trailing_newline(tmp_path: Path) -> None:
    record = {"pdf": entry("2026-10-01", A), "7z": entry("2026-10-02", B)}
    path = tmp_path / page_dates.FILE
    path.write_bytes(page_dates.render(record))
    assert page_dates.load(path) == record
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n") and text.index('"7z"') < text.index('"pdf"')


def test_no_record_is_an_empty_one_and_a_broken_one_is_refused(tmp_path: Path) -> None:
    assert page_dates.load(tmp_path / page_dates.FILE) == {}
    (tmp_path / page_dates.FILE).write_text('{"pdf": {"date": "2026-10-01"}}\n')
    with pytest.raises(ValueError, match="not a page-dates record"):
        page_dates.load(tmp_path / page_dates.FILE)


def test_a_stale_record_is_an_error_unless_asked_to_write(tmp_path: Path) -> None:
    path = tmp_path / page_dates.FILE
    record = {"pdf": entry("2026-10-01", A)}
    [error] = page_dates.settle(record, ["pdf"], path, write=False)
    assert "out of date for 1 page(s): pdf" in error and "--update-dates" in error
    assert not path.exists()
    assert page_dates.settle(record, ["pdf"], path, write=True) == []
    assert page_dates.load(path) == record
    assert page_dates.settle(record, [], tmp_path / "untouched.json", write=False) == []
    assert not (tmp_path / "untouched.json").exists(), "a current record is not rewritten"


# --- the trap: the date must not feed its own hash ---------------------------------------


def built(tmp_path: Path, name: str, committed: dt.datetime, previous: Any) -> Any:
    out = tmp_path / name / "site"
    return out, build.build(out, root=ROOT, committed=committed, previous=previous)


def lastmods(site: Path) -> dict[str, str]:
    rows = re.findall(
        r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>",
        (site / "sitemap.xml").read_text(encoding="utf-8"),
    )
    return {routes.key_for(url.removeprefix("https://loremfile.dev")): day for url, day in rows}


def page(site: Path, key: str) -> bytes:
    return (site / routes.disk_path(key)).read_bytes()


@pytest.fixture(scope="module")
def first(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    """A build from no record at all: every page new, every page dated DAY1."""
    return built(tmp_path_factory.mktemp("first"), "day1", DAY1, {})


def test_rebuilding_with_no_content_change_moves_no_date(
    tmp_path: Path, first: tuple[Path, Any]
) -> None:
    """The user-facing promise: a later deploy that changes nothing dates nothing."""
    site1, report1 = first
    assert set(report1.dates) == set(lastmods(site1)), "control: one entry per sitemap URL"
    assert {e.date for e in report1.dates.values()} == {DAY1.date()}
    site2, report2 = built(tmp_path, "day2", DAY2, report1.dates)
    assert report2.dates == report1.dates
    assert report2.stale == []
    assert lastmods(site2) == lastmods(site1)
    for key in ("pdf", "testing/uploads", "docs/faq", "index.html"):
        assert page(site2, key) == page(site1, key), key


def test_the_dated_page_really_differs_between_days(
    tmp_path: Path, first: tuple[Path, Any]
) -> None:
    """The control that makes the test above mean something: dated afresh on DAY2, a format
    page's bytes differ from DAY1's, so a hash of the dated page would have moved its date."""
    site1, _ = first
    site2, _ = built(tmp_path, "fresh", DAY2, {})
    assert page(site2, "pdf") != page(site1, "pdf")
    assert b'"dateModified":"2026-11-09"' in page(site2, "pdf")


def test_a_content_change_moves_only_that_pages_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: tuple[Path, Any]
) -> None:
    """The second control: real content does move a date, and only its own page's."""
    _, report1 = first
    original = build.content

    def edited(root: Path, relative: str) -> str:
        text = original(root, relative)
        return text + "\nOne more sentence.\n" if relative == "formats/pdf.md" else text

    monkeypatch.setattr(build, "content", edited)
    site2, report2 = built(tmp_path, "edited", DAY2, report1.dates)
    assert report2.stale == ["pdf"]
    days = lastmods(site2)
    assert days["pdf"] == "2026-11-09"
    assert {day for key, day in days.items() if key != "pdf"} == {"2026-11-02"}
    assert b'"dateModified":"2026-11-09"' in page(site2, "pdf")


# --- the committed record ----------------------------------------------------------------


def test_the_committed_record_is_current(tmp_path: Path) -> None:
    """What CI's `site build` also refuses: a page whose content changed without
    `--update-dates`. Its dates are what the sitemap carries, whatever the build's date."""
    committed = page_dates.load(ROOT / page_dates.FILE)
    for key in ("index.html", "pdf", "testing/uploads", "docs/faq", "changelog"):
        assert key in committed, key
    report = build.build(tmp_path / "site", root=ROOT, committed=DAY2)
    assert report.stale == [], "run `loremfile site build --update-dates` and commit the record"
    assert report.dates == committed
    assert not any(key.startswith("legal") for key in committed), "the legal pages date themselves"


@pytest.mark.parametrize("stale", [True, False], ids=["empty record", "committed record"])
def test_the_command_refuses_only_a_stale_record_and_never_writes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stale: bool
) -> None:
    """The real `site build`, with only the record it reads replaced by an empty one; the
    committed record is the control, so the refusal is about dates and nothing else."""
    before = (ROOT / page_dates.FILE).read_bytes()
    if stale:
        monkeypatch.setattr(page_dates, "load", lambda _path: {})
    result = CliRunner().invoke(
        cli.main, ["site", "build", "--out", str(tmp_path / "site"), "--json"]
    )
    errors = json.loads(result.stdout)["errors"]
    refused = any("page-dates.json is out of date" in e and "--update-dates" in e for e in errors)
    assert refused is stale, errors
    assert (result.exit_code != 0) is stale, errors
    assert (ROOT / page_dates.FILE).read_bytes() == before
