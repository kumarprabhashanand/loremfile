"""The legal pages' values and their count-only guards (ADR-028, docs/13 §3b).

Every value in this file is invented. The point of these tests is that no report, message or
error ever contains a value, whatever goes wrong.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from loremfile.site import legal, routes

VALUES = {
    "IMPRINT_NAME": "Test Operator & Co",
    "IMPRINT_STREET": "Example Street 1",
    "IMPRINT_POSTAL_CITY": "00000 Example City",
}
PLACEHOLDERS = "%%IMPRINT_NAME%%<br>%%IMPRINT_STREET%%<br>%%IMPRINT_POSTAL_CITY%%"


@pytest.fixture
def site(tmp_path: Path) -> Path:
    root = tmp_path / "site"
    pages = {
        "legal/imprint": f"<p>{PLACEHOLDERS}</p>",
        "legal/privacy": f"<p>Controller: {PLACEHOLDERS}</p>",
        "index.html": "<p>home</p>",
        "formats": "<p>formats</p>",
        "llms.txt": "# loremfile.dev\n",
    }
    for key, body in pages.items():
        path = root / routes.disk_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def never(_value: str) -> bool:
    return False


def shown(report: legal.LegalReport) -> str:
    return " ".join([*report.problems, report.render()])


def test_the_values_fill_exactly_the_two_pages_escaped(site: Path) -> None:
    assert legal.fill(site, VALUES) == 6
    imprint = (site / "legal" / "imprint.html").read_text()
    assert "Test Operator &amp; Co" in imprint
    assert "%%IMPRINT_" not in imprint
    report = legal.audit(site, VALUES, in_git=never)
    assert report.problems == []
    assert (site / "formats.html").read_text() == "<p>formats</p>"


def test_a_missing_or_empty_secret_is_named_and_no_value_is_shown() -> None:
    with pytest.raises(legal.LegalError, match="IMPRINT_STREET") as caught:
        legal.values_from({**VALUES, "IMPRINT_STREET": "  "})
    assert all(value not in str(caught.value) for value in VALUES.values())
    with pytest.raises(legal.LegalError, match="IMPRINT_NAME"):
        legal.values_from({})


@pytest.mark.parametrize(
    "body", ["Example Street 1", "Test Operator &amp; Co"], ids=["raw", "escaped"]
)
def test_a_value_in_any_other_key_is_counted_and_never_shown(site: Path, body: str) -> None:
    legal.fill(site, VALUES)
    (site / "llms.txt").write_text(f"# loremfile.dev\n{body}\n")
    report = legal.audit(site, VALUES, in_git=never)
    assert report.other_keys_with_a_value == 1
    assert all(value not in shown(report) for value in VALUES.values())


def test_unfilled_pages_fail_both_guards(site: Path) -> None:
    report = legal.audit(site, VALUES, in_git=never)
    assert report.placeholders_left == 2
    assert report.pages_missing_a_value == 2
    assert sorted(legal.leftover_placeholders(site)) == sorted(routes.LEGAL_KEYS)


def test_a_value_committed_to_git_fails(site: Path) -> None:
    legal.fill(site, VALUES)
    report = legal.audit(site, VALUES, in_git=lambda value: value == VALUES["IMPRINT_STREET"])
    assert report.values_in_git == 1
    assert any("open an incident" in problem for problem in report.problems)
    assert all(value not in shown(report) for value in VALUES.values())


def test_git_grep_finds_a_committed_value_and_not_an_absent_one(tmp_path: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    (tmp_path / "notes.txt").write_text("needle-4711\n")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "x"]):
        subprocess.run(  # noqa: S603 - fixed argv
            [
                git,
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.invalid",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
    assert legal.in_repository("needle-4711", cwd=tmp_path) is True
    assert legal.in_repository("absent-0815", cwd=tmp_path) is False
