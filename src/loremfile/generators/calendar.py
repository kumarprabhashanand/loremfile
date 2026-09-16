"""Calendar and contact fixtures — ics and vcf (docs/05 §3.11).

Both formats are line-based text with their own folding rules, and both normally carry a
stamp from the machine that wrote them: `DTSTAMP` in a calendar, `REV` in a contact. Those
are fixed here, as are every UID and the product identifier, so the same fixture is the
same bytes on every build.

The calendars are built with `icalendar`; the contacts are written directly, because a
vCard is a short line format and writing it by hand keeps the folding explicit and the
bytes stable. Both are read back by an independent library in the validator.
"""

from __future__ import annotations

import datetime as dt

from icalendar import Calendar, Event

from loremfile.generators.base import GeneratorContext, generator
from loremfile.util import lorem

PRODID = "-//loremfile//fixtures//EN"
START = dt.datetime(2020, 1, 1, 9, 0, tzinfo=dt.UTC)
STAMP = dt.datetime(2020, 1, 1, 0, 0, tzinfo=dt.UTC)
DOMAIN = "example.com"
#: vCard and iCalendar both fold long lines at 75 octets, continued by a leading space.
FOLD_AT = 75


def _uid(ctx: GeneratorContext, index: int = 0) -> str:
    return f"{ctx.seed.hex()[:24]}{index:04d}@{DOMAIN}"


def _calendar() -> Calendar:
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    return calendar


def _event(ctx: GeneratorContext, index: int, summary: str) -> Event:
    event = Event()
    event.add("uid", _uid(ctx, index))
    event.add("dtstamp", STAMP)
    event.add("summary", summary)
    return event


@generator()
def ics_single_event(ctx: GeneratorContext) -> bytes:
    """One timed event with a description and a location."""
    calendar = _calendar()
    event = _event(ctx, 0, "Quarterly fixture review")
    event.add("dtstart", START)
    event.add("dtend", START + dt.timedelta(hours=1))
    event.add("description", lorem.sentence(ctx.rng))
    event.add("location", "Room 1")
    calendar.add_component(event)
    return bytes(calendar.to_ical())


@generator()
def ics_recurring(ctx: GeneratorContext, *, count: int = 10) -> bytes:
    """A weekly series expressed as one event plus an RRULE, not as `count` events."""
    calendar = _calendar()
    event = _event(ctx, 0, "Weekly fixture stand-up")
    event.add("dtstart", START)
    event.add("dtend", START + dt.timedelta(minutes=30))
    event.add("rrule", {"freq": "weekly", "count": count, "byday": "WE"})
    calendar.add_component(event)
    return bytes(calendar.to_ical())


def _fold(line: str) -> str:
    """Fold one content line at 75 octets, continuation lines starting with a space."""
    raw = line.encode("utf-8")
    if len(raw) <= FOLD_AT:
        return line
    chunks, rest = [raw[:FOLD_AT]], raw[FOLD_AT:]
    while rest:
        chunks.append(rest[: FOLD_AT - 1])
        rest = rest[FOLD_AT - 1 :]
    return "\r\n ".join(chunk.decode("utf-8", "surrogatepass") for chunk in chunks)


def _card(lines: list[str]) -> str:
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _person(index: int) -> tuple[str, str, str]:
    """A synthetic contact: family name, given name and the local part of its address."""
    families = ["Fixture", "Sample", "Example", "Placeholder", "Lorem"]
    givens = ["Alex", "Sam", "Robin", "Kim", "Jo"]
    family = families[index % len(families)]
    given = givens[(index // len(families)) % len(givens)]
    return family, given, f"{given.lower()}.{family.lower()}{index}"


@generator()
def vcard3(ctx: GeneratorContext) -> bytes:
    """A vCard 3.0 contact, the version most address books still export."""
    family, given, local = _person(0)
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{family};{given};;;",
        f"FN:{given} {family}",
        "ORG:loremfile fixtures",
        "TITLE:Test Contact",
        f"EMAIL;TYPE=INTERNET:{local}@{DOMAIN}",
        "TEL;TYPE=WORK,VOICE:+49 30 901820",
        f"URL:https://{DOMAIN}/",
        f"NOTE:{lorem.sentence(ctx.rng)}",
        f"UID:{_uid(ctx)}",
        "REV:2020-01-01T00:00:00Z",
        "END:VCARD",
    ]
    return _card(lines).encode("utf-8")


@generator()
def vcard4(ctx: GeneratorContext) -> bytes:
    """A vCard 4.0 contact: typed values and URI-shaped properties (RFC 6350)."""
    family, given, local = _person(1)
    lines = [
        "BEGIN:VCARD",
        "VERSION:4.0",
        f"N:{family};{given};;;",
        f"FN:{given} {family}",
        "KIND:individual",
        "ORG:loremfile fixtures",
        f"EMAIL;TYPE=work:{local}@{DOMAIN}",
        'TEL;VALUE=uri;TYPE="work,voice":tel:+49-30-901820',
        f"URL:https://{DOMAIN}/",
        "LANG;PREF=1:en",
        f"NOTE:{lorem.sentence(ctx.rng)}",
        f"UID:urn:uuid:{ctx.seed.hex()[:8]}-{ctx.seed.hex()[8:12]}-4{ctx.seed.hex()[13:16]}"
        f"-8{ctx.seed.hex()[17:20]}-{ctx.seed.hex()[20:32]}",
        "REV:20200101T000000Z",
        "END:VCARD",
    ]
    return _card(lines).encode("utf-8")
