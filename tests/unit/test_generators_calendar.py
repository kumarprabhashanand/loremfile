"""M3.7 calendars and contacts: ics and vcf, and the stamps that would otherwise drift.

Both formats normally record when they were written — `DTSTAMP` in a calendar, `REV` in a
contact — and both fold long lines at 75 octets with CRLF endings. The generators pin the
first and obey the second; the tests below drive a file with each rule broken, so the
validator is shown failing rather than assumed to work.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from icalendar import Calendar

from loremfile.catalog import Catalog, Fixture
from loremfile.generators import calendar as calendar_generators
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import calendar as calendar_validators  # noqa: F401 - registers them
from loremfile.validators import validate

CATALOG = Catalog.load()
WORKDIR = Path(tempfile.gettempdir())
#: Built in CI, where the published PNG it embeds can be resolved.
NEEDS_PUBLISHED = {"vcf/with-photo.vcf"}
PNG = bytes.fromhex("89504e470d0a1a0a") + b"not a real png, only the bytes to embed"


def fixture(path: str) -> Fixture:
    return CATALOG.by_path[path]


def build(path: str) -> bytes:
    entry = fixture(path)
    ctx = GeneratorContext(path=path, workdir=WORKDIR, _dependency=lambda _p: PNG)
    with deterministic(ctx.seed):
        out = REGISTRY.get(entry.generator)(ctx, **entry.params)
    assert isinstance(out, bytes)
    return out


def check(path: str, payload: bytes | None = None) -> dict:
    entry = fixture(path)
    report = validate(
        payload if payload is not None else build(path), entry, CATALOG.mime_for(entry)
    )
    assert report.ok, report.failures
    return report.props


def refused(path: str, payload: bytes) -> str:
    entry = fixture(path)
    report = validate(payload, entry, CATALOG.mime_for(entry))
    assert not report.ok, f"{path} accepted a file it should refuse"
    return " | ".join(report.failures)


def paths() -> list[str]:
    return [f.path for f in CATALOG.fixtures() if f.format in {"ics", "vcf"}]


def test_the_calendar_and_contact_formats_are_catalogued() -> None:
    """Empty-set control: the parametrised tests below check nothing without these rows."""
    assert len([p for p in paths() if p.startswith("ics/")]) == 2
    assert len([p for p in paths() if p.startswith("vcf/")]) == 2


@pytest.mark.parametrize("path", paths(), ids=lambda path: path)
def test_a_file_is_byte_identical_on_a_second_build(path: str) -> None:
    assert build(path) == build(path)


@pytest.mark.parametrize("path", paths(), ids=lambda path: path)
def test_a_file_validates_against_its_catalog_entry(path: str) -> None:
    check(path)


@pytest.mark.parametrize("path", paths(), ids=lambda path: path)
def test_every_line_ends_with_crlf_and_fits_the_fold(path: str) -> None:
    data = build(path)
    assert b"\r\n" in data
    assert all(len(line) <= 75 for line in data.split(b"\r\n")), "lines must fold at 75 octets"


# --- calendars -------------------------------------------------------------


def test_the_series_is_one_event_with_a_rule_not_ten_events() -> None:
    props = check("ics/recurring-weekly-rrule.ics")
    assert props["events"] == 1
    assert props["recurring"] is True
    calendar = Calendar.from_ical(build("ics/recurring-weekly-rrule.ics"))
    rule = next(c for c in calendar.walk() if c.name == "VEVENT")["rrule"]
    assert rule["FREQ"] == ["WEEKLY"]
    assert rule["COUNT"] == [10]


# --- contacts --------------------------------------------------------------


def test_the_two_vcard_versions_say_which_they_are() -> None:
    assert check("vcf/vcard3-single.vcf")["version"] == "3.0"
    assert check("vcf/vcard4-single.vcf")["version"] == "4.0"


# --- negative tests --------------------------------------------------------


def test_a_calendar_stamped_by_the_clock_is_refused() -> None:
    data = build("ics/single-event.ics").replace(
        b"DTSTAMP:20200101T000000Z", b"DTSTAMP:20260916T070000Z"
    )
    assert "DTSTAMP" in refused("ics/single-event.ics", data)


def test_a_calendar_with_another_product_id_is_refused() -> None:
    data = build("ics/single-event.ics").replace(
        calendar_generators.PRODID.encode(), b"-//Someone Else//EN"
    )
    assert "PRODID" in refused("ics/single-event.ics", data)


def test_a_calendar_with_bare_newlines_is_refused() -> None:
    data = build("ics/single-event.ics").replace(b"\r\n", b"\n")
    assert "CRLF" in refused("ics/single-event.ics", data)


def test_a_contact_with_a_clock_rev_is_refused() -> None:
    data = build("vcf/vcard3-single.vcf").replace(
        b"REV:2020-01-01T00:00:00Z", b"REV:2026-09-16T07:00:00Z"
    )
    assert "REV" in refused("vcf/vcard3-single.vcf", data)


def test_a_contact_without_a_full_name_is_refused() -> None:
    data = (
        b"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:x@example.com\r\n"
        b"REV:2020-01-01T00:00:00Z\r\nEND:VCARD\r\n"
    )
    assert "FN" in refused("vcf/vcard3-single.vcf", data)
