"""Validators for the calendar and contact formats (docs/06 §6).

Each file is read back by a library that did not write it — `icalendar` for calendars,
`vobject` for contacts — and described by what that reader found. The timestamps get their
own check: `DTSTAMP` in a calendar and `REV` in a contact are what a writer fills from the
clock, and a fixture whose hash moves every build is not a fixture.
"""

from __future__ import annotations

import re
from typing import Any

import vobject
from icalendar import Calendar

from loremfile.catalog import Fixture
from loremfile.generators.calendar import PRODID, STAMP
from loremfile.validators import ValidationError, register

FIXED_STAMP = STAMP.strftime("%Y%m%dT%H%M%SZ").encode()
FIXED_REV = re.compile(rb"^REV:2020-01-01T00:00:00Z|^REV:20200101T000000Z", re.M)
#: Both formats fold at 75 octets and separate lines with CRLF (RFC 5545, RFC 6350).
CRLF = b"\r\n"


@register("ics")
def validate_ics(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
    try:
        calendar = Calendar.from_ical(data)
    except ValueError as exc:
        raise ValidationError(f"is not a readable calendar: {exc}") from exc

    events = [component for component in calendar.walk() if component.name == "VEVENT"]
    zones = [component for component in calendar.walk() if component.name == "VTIMEZONE"]
    if not events:
        raise ValidationError("holds no VEVENT, so there is nothing for a client to show")
    if str(calendar.get("prodid")) != PRODID:
        raise ValidationError(f"PRODID is {calendar.get('prodid')!r}, not the fixed {PRODID!r}")
    if CRLF not in data:
        raise ValidationError("uses bare newlines; RFC 5545 requires CRLF")
    for event in events:
        if not event.get("uid"):
            raise ValidationError("an event has no UID")
        if FIXED_STAMP not in event.to_ical():
            raise ValidationError("an event's DTSTAMP is not the fixed one, so the hash drifts")

    first = events[0]
    return {
        "events": len(events),
        "timezones": len(zones),
        "recurring": any(event.get("rrule") for event in events),
        "all_day": not hasattr(first.get("dtstart").dt, "hour"),
        "timezone_ids": sorted(str(zone.get("tzid")) for zone in zones),
    }


@register("vcf")
def validate_vcf(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
    text = data.decode("utf-8")
    try:
        cards = list(vobject.readComponents(text))
    except Exception as exc:  # vobject raises several unrelated types
        raise ValidationError(f"is not a readable vCard: {exc}") from exc
    if not cards:
        raise ValidationError("holds no vCard")
    if CRLF not in data:
        raise ValidationError("uses bare newlines; RFC 6350 requires CRLF")
    if not FIXED_REV.search(data):
        raise ValidationError("REV is not the fixed timestamp, so the hash drifts")

    for card in cards:
        if not hasattr(card, "fn"):
            raise ValidationError("a card has no FN, which every vCard must carry")
        if not hasattr(card, "uid"):
            raise ValidationError("a card has no UID")
    over_length = [line for line in text.split("\r\n") if len(line.encode()) > 75]  # noqa: PLR2004
    if over_length:
        raise ValidationError(f"{len(over_length)} line(s) are longer than the 75-octet fold")

    first = cards[0]
    return {
        "cards": len(cards),
        "version": str(first.version.value),
        "has_photo": any(hasattr(card, "photo") for card in cards),
        "fn": str(first.fn.value),
    }
