"""M3.2a data formats: generators, validators, negative tests, determinism tests.

The cross-format property matters most here: every `people-N` fixture, in every format,
must serialise the *same* rows. A test that only checked each format in isolation would
miss the one thing these fixtures exist to provide.
"""

from __future__ import annotations

import csv as csv_module
import io
import json
import tempfile
import tomllib
from pathlib import Path

import pytest
import yaml

from loremfile import datasets
from loremfile.build import load_generators
from loremfile.catalog import Catalog, Fixture
from loremfile.generators import data
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import ValidationError, load, validate
from loremfile.validators.data import _measure_depth

WORKDIR = Path(tempfile.gettempdir())
CATALOG = Catalog.load()
load_generators()
load()


def ctx(path: str) -> GeneratorContext:
    return GeneratorContext(path=path, workdir=WORKDIR)


def fixture(path: str) -> Fixture:
    return CATALOG.by_path[path]


def build(path: str) -> bytes:
    """Generate a catalogue fixture exactly as the build would."""
    entry = fixture(path)
    context = ctx(path)
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **entry.params)
    assert isinstance(out, bytes)
    return out


def check(path: str, payload: bytes | None = None) -> dict:
    entry = fixture(path)
    report = validate(
        payload if payload is not None else build(path), entry, CATALOG.mime_for(entry)
    )
    assert report.ok, report.failures
    return report.props


# --- the cross-format promise ---------------------------------------------


def test_the_same_person_appears_identically_in_every_format() -> None:
    """csv, json, ndjson, xml and sql must all serialise the same first row."""
    person = data.to_jsonable(datasets.rows("people", 1)[0])

    csv_rows = list(csv_module.reader(io.StringIO(build("csv/people-10.csv").decode())))
    csv_first = dict(zip(csv_rows[0], csv_rows[1], strict=True))
    json_first = json.loads(build("json/people-10.json"))[0]
    ndjson_first = json.loads(build("ndjson/people-1000.ndjson").split(b"\n")[0])
    xml_text = build("xml/people-10.xml").decode()
    sql_text = build("sql/people-1000-inserts-portable.sql").decode()

    for record in (json_first, ndjson_first):
        assert record["id"] == person["id"]
        assert record["email"] == person["email"]
        assert record["city"] == person["city"]
    assert csv_first["email"] == person["email"]
    assert csv_first["id"] == str(person["id"])
    assert f"<email>{person['email']}</email>" in xml_text
    assert person["email"] in sql_text


def test_prefix_property_survives_serialisation() -> None:
    """people-10 must be the first ten rows of people-1000, in every format."""
    ten = json.loads(build("json/people-10.json"))
    thousand = json.loads(build("json/people-1000.json"))
    assert ten == thousand[:10]

    csv_10 = build("csv/people-10.csv").decode().splitlines()
    csv_1000 = build("csv/people-1000.csv").decode().splitlines()
    assert csv_10 == csv_1000[:11], "header plus ten rows"


# --- csv and tsv -----------------------------------------------------------


def test_csv_has_a_header_and_the_expected_shape() -> None:
    props = check("csv/people-10.csv")
    assert props["rows"] == 10
    assert props["columns"] == len(data.PEOPLE_COLUMNS)
    assert props["has_header"] is True
    assert props["delimiter"] == ","


def test_semicolon_variant_uses_semicolons() -> None:
    payload = build("csv/people-10-semicolon.csv").decode()
    assert payload.splitlines()[0].count(";") == len(data.PEOPLE_COLUMNS) - 1
    assert check("csv/people-10-semicolon.csv")["delimiter"] == ";"


def test_bom_variant_starts_with_a_bom_and_still_parses() -> None:
    payload = build("csv/people-10-utf8-bom.csv")
    assert payload.startswith(b"\xef\xbb\xbf")
    assert check("csv/people-10-utf8-bom.csv")["bom"] is True


def test_quoted_newlines_variant_really_contains_a_quoted_newline() -> None:
    payload = build("csv/people-10-quoted-newlines.csv").decode()
    # More physical lines than records: the newline is inside a quoted field.
    records = list(csv_module.reader(io.StringIO(payload)))
    assert len(payload.splitlines()) > len(records)
    assert check("csv/people-10-quoted-newlines.csv")["quoted_fields"] is True


def test_tsv_is_tab_delimited() -> None:
    assert check("tsv/people-1000.tsv")["delimiter"] == "\t"


def test_sized_csv_lands_inside_the_tolerance_and_stays_a_prefix() -> None:
    payload = build("csv/1mb.csv")
    assert abs(len(payload) - 1_000_000) <= 0.05 * 1_000_000
    rows = list(csv_module.reader(io.StringIO(payload.decode())))
    small = list(csv_module.reader(io.StringIO(build("csv/people-10.csv").decode())))
    assert rows[: len(small)] == small


# --- json ------------------------------------------------------------------


def test_json_people_is_an_array_of_objects() -> None:
    props = check("json/people-10.json")
    assert props["top_type"] == "array"
    assert props["items"] == 10


def test_all_types_covers_the_awkward_cases() -> None:
    text = build("json/all-types.json").decode()
    payload = json.loads(text)
    assert payload["null"] is None
    assert payload["big_integer"] == 9007199254740993
    assert payload["beyond_int64"] == 9223372036854775808
    assert payload["surrogate_pair"] == "\U0001f600"
    assert payload["empty_object"] == {} and payload["empty_array"] == []
    # Forms that must survive as written, not as Python would re-emit them.
    assert "-0.0" in text and "1.5e308" in text and "5e-324" in text
    check("json/all-types.json")


def test_nested_100_levels_is_exactly_100() -> None:
    assert check("json/nested-100-levels.json")["max_depth"] == 100


def test_depth_counts_containers_not_scalars() -> None:
    assert _measure_depth("x") == 0
    assert _measure_depth({"a": 1}) == 1
    assert _measure_depth({"a": {"b": 1}}) == 2
    assert _measure_depth([[[]]]) == 3


def test_sized_json_lands_inside_the_tolerance() -> None:
    payload = build("json/1mb.json")
    assert abs(len(payload) - 1_000_000) <= 0.05 * 1_000_000


def test_ndjson_is_one_object_per_line() -> None:
    payload = build("ndjson/people-1000.ndjson")
    lines = payload.decode().splitlines()
    assert len(lines) == 1000
    assert all(json.loads(line)["id"] == n + 1 for n, line in enumerate(lines[:20]))
    assert check("ndjson/people-1000.ndjson")["items"] == 1000


# --- xml, yaml, toml, sql --------------------------------------------------


def test_xml_people_parses_and_names_its_root() -> None:
    assert check("xml/people-10.xml")["root_element"] == "people"


def test_namespaces_are_reported() -> None:
    props = check("xml/with-namespaces.xml")
    assert "http://purl.org/dc/elements/1.1/" in props["namespaces"]
    assert "https://loremfile.dev/ns/catalogue" in props["namespaces"]


def test_rss_feed_is_wellformed_rss() -> None:
    props = check("xml/rss2-feed.xml")
    assert props["root_element"] == "rss"
    assert build("xml/rss2-feed.xml").decode().count("<item>") == 10


def test_yaml_has_two_documents_and_working_anchors() -> None:
    payload = build("yaml/config-all-types.yaml")
    documents = list(yaml.safe_load_all(payload.decode()))
    assert len(documents) == 2
    # The merge key must actually have merged.
    assert documents[0]["production"]["adapter"] == "postgres"
    assert documents[0]["production"]["pool"] == 25, "the override must win"
    assert documents[0]["types"]["bool_true"] is True
    assert documents[0]["types"]["null_value"] is None
    assert "\n" in documents[0]["block_literal"], "literal block keeps line breaks"
    check("yaml/config-all-types.yaml")


def test_toml_parses_with_the_standard_library() -> None:
    payload = tomllib.loads(build("toml/config.toml").decode())
    assert payload["server"]["port"] == 8080
    assert payload["server"]["max_bytes"] == 100_000_000
    assert len(payload["endpoints"]) == 2
    assert payload["server"]["limits"]["burst"] == 300
    check("toml/config.toml")


def test_sql_is_portable_and_quotes_correctly() -> None:
    text = build("sql/people-1000-inserts-portable.sql").decode()
    assert text.count("INSERT INTO people") == 1000
    assert "CREATE TABLE people" in text
    for vendorism in ("AUTO_INCREMENT", "SERIAL", "ENGINE=", "IF NOT EXISTS", "`"):
        assert vendorism not in text, f"{vendorism} is not portable"
    check("sql/people-1000-inserts-portable.sql")


def test_sql_escapes_embedded_apostrophes() -> None:
    """A bio containing an apostrophe must be doubled, not left to break the statement."""
    rows = [dict.fromkeys(data.PEOPLE_COLUMNS, "")]
    rows[0].update({"id": 1, "bio": "it's fine"})
    context = GeneratorContext(
        path="sql/x.sql", workdir=WORKDIR, _dataset=lambda _name, _count: rows
    )
    assert "'it''s fine'" in data.sql_inserts(context, rows=1).decode()


# --- determinism -----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "csv/people-10.csv",
        "csv/people-10-quoted-newlines.csv",
        "tsv/people-1000.tsv",
        "json/people-10.json",
        "json/all-types.json",
        "json/nested-100-levels.json",
        "ndjson/people-1000.ndjson",
        "xml/people-10.xml",
        "xml/with-namespaces.xml",
        "xml/rss2-feed.xml",
        "yaml/config-all-types.yaml",
        "toml/config.toml",
        "sql/people-1000-inserts-portable.sql",
        "csv/1mb.csv",
        "json/1mb.json",
    ],
)
def test_running_twice_gives_identical_bytes(path: str) -> None:
    assert build(path) == build(path)


# --- negative tests --------------------------------------------------------


def test_ragged_csv_is_rejected() -> None:
    entry = fixture("csv/people-10.csv")
    broken = b"a,b,c\n1,2,3\n4,5\n"
    report = validate(broken, entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("ragged" in f for f in report.failures)


def test_invalid_json_is_rejected() -> None:
    entry = fixture("json/people-10.json")
    report = validate(b'{"a": 1,}\n', entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("not valid JSON" in f for f in report.failures)


def test_a_single_bad_ndjson_line_is_rejected() -> None:
    entry = fixture("ndjson/people-1000.ndjson")
    payload = build("ndjson/people-1000.ndjson").split(b"\n")
    payload[500] = b"{not json"
    report = validate(b"\n".join(payload), entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("line 501" in f for f in report.failures)


def test_malformed_xml_is_rejected() -> None:
    entry = fixture("xml/people-10.xml")
    report = validate(b"<people><person></people>\n", entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("well-formed" in f for f in report.failures)


def test_xml_validator_does_not_resolve_external_entities() -> None:
    """An XXE payload must not reach the filesystem, and must not silently pass."""
    entry = fixture("xml/people-10.xml")
    payload = (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE people [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
        b"<people>&xxe;</people>\n"
    )
    report = validate(payload, entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("external entity" in f for f in report.failures), report.failures


def test_invalid_yaml_is_rejected() -> None:
    entry = fixture("yaml/config-all-types.yaml")
    report = validate(b"a:\n  - b\n - c\n", entry, CATALOG.mime_for(entry))
    assert not report.ok


def test_invalid_toml_is_rejected() -> None:
    entry = fixture("toml/config.toml")
    report = validate(b"key = \n", entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("not valid TOML" in f for f in report.failures)


def test_depth_guard_refuses_absurd_nesting() -> None:
    payload: object = "leaf"
    for _ in range(20_000):
        payload = [payload]
    with pytest.raises(ValidationError, match="deeper than the guard"):
        _measure_depth(payload)
