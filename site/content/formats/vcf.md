vCards are what address books exchange, and the two versions still in circulation are
different enough to break code written for only one of them.

`vcf/vcard3-single.vcf` is a version 3.0 contact with a name, organisation, email, telephone,
URL and note — the shape most exporters still produce. `vcf/vcard4-single.vcf` is the same
sort of contact expressed the way RFC 6350 introduced: typed, URI-shaped properties that a
3.0-only parser will not recognise.

Every line is folded at 75 octets as the specification requires, which is itself worth
testing: unfolding is a step that naive readers skip, and a folded line read literally turns
into a truncated value plus a stray continuation.

The contacts are synthetic. Names, addresses and telephone numbers are generated, and no real
person's details appear in any fixture here.

Use them to test contact imports, CRM ingestion, and conversion between vCard versions.
Related formats: [iCalendar](/ics) and [text files](/txt).
