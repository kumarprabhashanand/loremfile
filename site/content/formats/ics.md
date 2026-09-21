iCalendar files are exchanged between every calendar application, and the corners where
implementations disagree are well known: time zones, all-day events and recurrence.

`ics/single-event.ics` is the simple case — one timed event of an hour with a summary,
description and location, in UTC. `ics/recurring-weekly-rrule.ics` is the one that finds bugs:
a weekly series of ten occurrences expressed as a single event plus an `RRULE`, which the
client has to expand itself. Code that only reads `DTSTART` shows one event where there should
be ten.

Every line is folded at 75 octets as the specification requires, and nothing in either file
comes from the machine that generated it: timestamps and UIDs are derived from a seed, so the
files are byte for byte identical on every build and contain no personal data.

Use them to test calendar imports, invitation parsing and anything that has to expand a
recurrence rule correctly. Related formats: [vCard](/vcf) and [text files](/txt).
