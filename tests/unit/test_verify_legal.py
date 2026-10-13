"""verify-live's legal checks: the pages' values on production, never shown (ADR-028).

Driven with the real site build, filled with invented values, so the patterns are pinned to
the markup the build writes; then with every answer they exist to catch. Every scenario
also asserts that no finding carries a value, raw or escaped.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner

from loremfile import cli
from loremfile.infra import verify_live
from loremfile.infra.verify_live import Finding, Response, Status
from loremfile.site import build, legal, routes

ROOT = Path(__file__).resolve().parents[2]
VALUES = {
    "IMPRINT_NAME": "Test Operator & Co",
    "IMPRINT_STREET": "Example Street 1",
    "IMPRINT_POSTAL_CITY": "00000 Example City",
}
FORMS = {form for value in VALUES.values() for form in (value, html.escape(value, quote=True))}


@pytest.fixture(scope="module")
def pages(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    """Public path -> body, for the pages the legal checks read, as production serves them."""
    out = tmp_path_factory.mktemp("legal") / "site"
    build.build(out, root=ROOT, committed=dt.datetime(2026, 10, 13, tzinfo=dt.UTC))
    legal.fill(out, VALUES)
    keys = (*routes.LEGAL_KEYS, "legal/terms", "legal/license", "legal")
    return {routes.public_path(key): (out / routes.disk_path(key)).read_bytes() for key in keys}


def serve(
    pages: dict[str, bytes], **overrides: Response | Callable[[bytes], bytes]
) -> Callable[..., Response]:
    """A fake `fetch`: the given pages answer 200, anything else 404, unless overridden."""

    def fetch(path: str, **_kwargs: object) -> Response:
        override = overrides.get(path)
        if isinstance(override, Response):
            return override
        if path not in pages:
            return Response(404, {})
        body = pages[path]
        return Response(200, {}, override(body) if override else body)

    return fetch


def findings(monkeypatch: pytest.MonkeyPatch, fetch: Callable[..., Response]) -> list[Finding]:
    monkeypatch.setattr(verify_live, "fetch", fetch)
    found = verify_live.legal_findings()
    shown = json.dumps([[f.path, f.status.value, f.detail] for f in found])
    assert not any(form in shown for form in FORMS), "a finding carries a value"
    report = verify_live.LiveReport(found)
    assert not any(form in report.render() for form in FORMS)
    return found


def by_name(found: list[Finding]) -> dict[str, Finding]:
    return {f.path: f for f in found}


def replace(old: str, new: str) -> Callable[[bytes], bytes]:
    def edit(body: bytes) -> bytes:
        assert old.encode() in body, f"the build no longer writes {old!r}"
        return body.replace(old.encode(), new.encode(), 1)

    return edit


ESCAPED_NAME = html.escape(VALUES["IMPRINT_NAME"], quote=True)
COMPARISONS = (
    "legal:same-controller /legal/privacy",
    "legal:no-street /legal/privacy",
    "legal:no-postal-city /legal/privacy",
    "legal:no-value /legal/terms",
    "legal:no-value /legal/license",
    "legal:no-value /legal",
)


def test_production_s_shape_passes_every_check(
    monkeypatch: pytest.MonkeyPatch, pages: dict[str, bytes]
) -> None:
    found = by_name(findings(monkeypatch, serve(pages)))
    named = {
        "legal:filled /legal/imprint",
        "legal:filled /legal/privacy",
        "legal:imprint-lines /legal/imprint",
        "legal:controller-paragraph /legal/privacy",
        *COMPARISONS,
        "legal:no-twin /legal/privacy/index.md",
        "legal:no-twin /legal/imprint/index",
        "legal:no-twin /_formats/legal/privacy.md",
    }
    assert named <= set(found), "empty-set control: the checks the rest of this file needs"
    assert [f for f in found.values() if f.status is not Status.OK] == []


def test_the_twelve_twin_paths_cover_the_build_guard_and_both_pages() -> None:
    paths = verify_live.LEGAL_TWIN_PATHS
    assert len(paths) == len(set(paths)) == 12
    assert {routes.public_path(twin) for twin in routes.LEGAL_TWINS} <= set(paths)
    for page in ("imprint", "privacy"):
        assert {
            f"/legal/{page}.html",
            f"/legal/{page}/index.html",
            f"/_formats/legal/{page}.md",
        } <= set(paths)


def test_the_neighbours_are_every_legal_page_that_names_nobody() -> None:
    named = {routes.public_path(key) for key, _, _ in build.LEGAL} - {
        routes.public_path(key) for key in routes.LEGAL_KEYS
    }
    assert set(verify_live.LEGAL_NEIGHBOURS) == named | {"/legal"}


@pytest.mark.parametrize(
    ("value", "check"),
    [("IMPRINT_STREET", "no-street"), ("IMPRINT_POSTAL_CITY", "no-postal-city")],
)
def test_privacy_carrying_the_address_fails(
    monkeypatch: pytest.MonkeyPatch, pages: dict[str, bytes], value: str, check: str
) -> None:
    edit = replace("</main>", f"<p>{html.escape(VALUES[value])}</p></main>")
    found = by_name(findings(monkeypatch, serve(pages, **{"/legal/privacy": edit})))
    assert found[f"legal:{check} /legal/privacy"].status is Status.LEGAL_VALUE
    others = [f for name, f in found.items() if name != f"legal:{check} /legal/privacy"]
    assert all(f.status is Status.OK for f in others)


def test_privacy_naming_another_controller_fails(
    monkeypatch: pytest.MonkeyPatch, pages: dict[str, bytes]
) -> None:
    edit = replace(f"</strong> {ESCAPED_NAME} is", "</strong> Someone Else is")
    found = by_name(findings(monkeypatch, serve(pages, **{"/legal/privacy": edit})))
    assert found["legal:same-controller /legal/privacy"].status is Status.LEGAL_VALUE
    assert found["legal:controller-paragraph /legal/privacy"].status is Status.OK


def test_the_paragraph_before_86_fails_on_shape_street_and_city(
    monkeypatch: pytest.MonkeyPatch, pages: dict[str, bytes]
) -> None:
    """The text production served until 2026-10-13, as the old template rendered it."""
    street, city = (html.escape(VALUES[n]) for n in ("IMPRINT_STREET", "IMPRINT_POSTAL_CITY"))
    old = (
        f"<p><strong>Who is responsible.</strong> {ESCAPED_NAME}, {street}, {city}\n"
        "is the controller for the personal data described here. Contact: hello@loremfile.dev.</p>"
    )

    def edit(body: bytes) -> bytes:
        current = verify_live.PRIVACY_CONTROLLER.search(body.decode())
        assert current is not None
        return body.replace(current.group(0).encode(), old.encode())

    found = by_name(findings(monkeypatch, serve(pages, **{"/legal/privacy": edit})))
    assert found["legal:controller-paragraph /legal/privacy"].status is Status.LEGAL_VALUE
    assert found["legal:same-controller /legal/privacy"].status is Status.UNREADABLE
    assert found["legal:no-street /legal/privacy"].status is Status.LEGAL_VALUE
    assert found["legal:no-postal-city /legal/privacy"].status is Status.LEGAL_VALUE


@pytest.mark.parametrize("path", ["/legal/terms", "/legal/license", "/legal"])
def test_a_page_that_names_nobody_carrying_a_value_fails(
    monkeypatch: pytest.MonkeyPatch, pages: dict[str, bytes], path: str
) -> None:
    edit = replace("</main>", f"<p>{html.escape(VALUES['IMPRINT_POSTAL_CITY'])}</p></main>")
    found = by_name(findings(monkeypatch, serve(pages, **{path: edit})))
    assert found[f"legal:no-value {path}"].status is Status.LEGAL_VALUE


@pytest.mark.parametrize(
    "imprint",
    [
        Response(404, {}),
        Response(0, {}),
        Response(200, {}, b"<p>Impressum</p>"),
    ],
    ids=["404", "no-response", "markup-changed"],
)
def test_an_unreadable_imprint_means_every_comparison_could_not_run(
    monkeypatch: pytest.MonkeyPatch, pages: dict[str, bytes], imprint: Response
) -> None:
    """A check that cannot look has learned nothing; none of them may pass."""
    found = by_name(findings(monkeypatch, serve(pages, **{"/legal/imprint": imprint})))
    assert found["legal:imprint-lines /legal/imprint"].status is Status.UNREADABLE
    for name in COMPARISONS:
        assert found[name].status is Status.UNREADABLE, name


def unfilled(body: bytes) -> bytes:
    for name, value in VALUES.items():
        body = body.replace(html.escape(value, quote=True).encode(), f"%%{name}%%".encode())
    return body


def test_served_placeholders_fail_and_compare_nothing(
    monkeypatch: pytest.MonkeyPatch, pages: dict[str, bytes]
) -> None:
    """Otherwise a blank Impressum would pass: three non-empty lines, the same "name"."""
    overrides = {"/legal/imprint": unfilled, "/legal/privacy": unfilled}
    found = by_name(findings(monkeypatch, serve(pages, **overrides)))
    assert found["legal:filled /legal/imprint"].status is Status.LEGAL_VALUE
    assert found["legal:filled /legal/privacy"].status is Status.LEGAL_VALUE
    assert found["legal:imprint-lines /legal/imprint"].status is Status.UNREADABLE
    for name in COMPARISONS:
        assert found[name].status is Status.UNREADABLE, name


def test_an_imprint_line_left_blank_is_unreadable_too(
    monkeypatch: pytest.MonkeyPatch, pages: dict[str, bytes]
) -> None:
    street = html.escape(VALUES["IMPRINT_STREET"])
    edit = replace(f"{street}<br />", " <br />")
    found = by_name(findings(monkeypatch, serve(pages, **{"/legal/imprint": edit})))
    assert found["legal:imprint-lines /legal/imprint"].status is Status.UNREADABLE
    assert found["legal:no-street /legal/privacy"].status is Status.UNREADABLE


def test_an_unreachable_privacy_page_is_not_a_pass(
    monkeypatch: pytest.MonkeyPatch, pages: dict[str, bytes]
) -> None:
    found = by_name(findings(monkeypatch, serve(pages, **{"/legal/privacy": Response(503, {})})))
    assert found["legal:controller-paragraph /legal/privacy"].status is Status.STATUS
    assert found["legal:same-controller /legal/privacy"].status is Status.UNREADABLE
    assert found["legal:no-street /legal/privacy"].status is Status.UNREADABLE


@pytest.mark.parametrize(
    ("answer", "status"), [(200, Status.STATUS), (403, Status.STATUS), (0, Status.TIMEOUT)]
)
def test_a_twin_path_that_does_not_404_fails(
    monkeypatch: pytest.MonkeyPatch, pages: dict[str, bytes], answer: int, status: Status
) -> None:
    path = "/legal/privacy/index.md"
    found = by_name(findings(monkeypatch, serve(pages, **{path: Response(answer, {})})))
    assert found[f"legal:no-twin {path}"].status is status
    assert sum(f.status is not Status.OK for f in found.values()) == 1


@pytest.mark.parametrize(
    ("args", "expected"), [(["--mode", "smoke"], True), (["--only", "x"], False)]
)
def test_every_mode_runs_them_and_only_does_not(
    monkeypatch: pytest.MonkeyPatch, args: list[str], expected: bool
) -> None:
    asked: list[bool] = []
    monkeypatch.setattr(verify_live, "legal_findings", lambda: asked.append(True) or [])
    monkeypatch.setattr(verify_live, "contract_findings", lambda _e: [])
    monkeypatch.setattr(verify_live, "fetch", lambda _p, **_k: Response(404, {}))
    CliRunner().invoke(cli.main, ["verify-live", *args, "--json"])
    assert bool(asked) is expected


# --- the robots header and meta tag, both URL forms (check_page_headers) -----------------


def legal_page(*, robots: str = routes.LEGAL_ROBOTS, meta: bool = True) -> Response:
    headers = {**verify_live.EXPECTED_PAGE_HEADERS, "x-robots-tag": robots}
    body = (verify_live.LEGAL_META if meta else b"") + b"<main></main>"
    return Response(200, {k: v for k, v in headers.items() if v}, body)


def test_both_forms_of_both_pages_are_checked_for_robots_and_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = legal_page()
    digest = hashlib.sha256(good.body).hexdigest()
    hashes = dict.fromkeys(routes.LEGAL_KEYS, digest)
    responses = dict.fromkeys(routes.LEGAL_KEYS, good)
    monkeypatch.setattr(verify_live, "fetch", lambda _p, **_k: good)
    found = verify_live.header_branch_findings(hashes, responses)
    assert {f.path for f in found} == {
        "/legal/imprint",
        "/legal/imprint/",
        "/legal/privacy",
        "/legal/privacy/",
    }
    assert all(f.status is Status.OK for f in found)


@pytest.mark.parametrize(
    ("served", "status"),
    [
        (legal_page(robots=""), Status.HEADER_VALUE),
        (legal_page(robots="noindex"), Status.HEADER_VALUE),
        (legal_page(meta=False), Status.HEADER_MISSING),
    ],
    ids=["no-header", "noindex-only", "no-meta"],
)
def test_the_slash_form_without_its_robots_directive_fails(
    monkeypatch: pytest.MonkeyPatch, served: Response, status: Status
) -> None:
    good = legal_page()
    digest = hashlib.sha256(good.body).hexdigest()
    monkeypatch.setattr(verify_live, "fetch", lambda _p, **_k: served)
    found = verify_live.header_branch_findings(
        dict.fromkeys(routes.LEGAL_KEYS, digest), dict.fromkeys(routes.LEGAL_KEYS, good)
    )
    failing = {
        (f.path, f.status) for f in found if f.status not in {Status.OK, Status.HASH_MISMATCH}
    }
    assert failing == {("/legal/imprint/", status), ("/legal/privacy/", status)}


def test_the_documented_status_vocabulary_is_the_enum() -> None:
    """docs/06 §10 fixes it and the issue automation keys off it; `header_value` had drifted out."""
    text = (ROOT / "docs" / "06-generation-pipeline.md").read_text(encoding="utf-8")
    match = re.search(r"`verify-live` items use `status ∈ \{([^}]*)\}`", text)
    assert match is not None
    assert {part.strip() for part in match.group(1).split(",")} == {s.value for s in Status}
