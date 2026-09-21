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


# --- FORBIDDEN_STRINGS: the same count-only guard, for a denylist kept in a secret -------

#: Invented. The real list exists only in the production secret.
FORBIDDEN = ["forbidden-zone-4711.example", "Another Forbidden Name"]


def _repo(tmp_path: Path, text: str) -> Path:
    git = shutil.which("git")
    assert git is not None
    (tmp_path / "notes.txt").write_text(text)
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
    return tmp_path


def test_forbidden_strings_are_one_per_line_and_blank_lines_are_dropped() -> None:
    env = {"FORBIDDEN_STRINGS": "\n  forbidden-zone-4711.example  \r\n\n\nAnother Forbidden Name\n"}
    assert legal.forbidden_from(env) == FORBIDDEN
    assert legal.forbidden_from({}) == [], "the secret is optional"


def test_an_empty_pattern_matches_everything_which_is_why_blanks_are_dropped(
    tmp_path: Path,
) -> None:
    """The hazard the filter exists for, demonstrated rather than asserted: one stray blank
    line in the secret would otherwise fail every build."""
    repo = _repo(tmp_path, "nothing forbidden here\n")
    assert legal.in_repository("", cwd=repo) is True


def test_a_forbidden_string_in_the_tree_fails_and_is_never_shown(site: Path) -> None:
    legal.fill(site, VALUES)
    report = legal.audit(
        site,
        VALUES,
        in_git=never,
        forbidden=FORBIDDEN,
        forbidden_in_git=lambda text: text == FORBIDDEN[1],
    )
    assert (report.forbidden_checked, report.forbidden_in_git) == (2, 1)
    assert any("FORBIDDEN_STRINGS" in problem for problem in report.problems)
    assert all(text not in shown(report) for text in FORBIDDEN), "a denylist entry was printed"


def test_without_the_secret_nothing_is_checked_and_nothing_fails(site: Path) -> None:
    legal.fill(site, VALUES)
    report = legal.audit(site, VALUES, in_git=never)
    assert (report.forbidden_checked, report.forbidden_in_git) == (0, 0)
    assert not any("FORBIDDEN_STRINGS" in problem for problem in report.problems)
    assert "forbidden strings 0 checked" in report.render(), "the scope stays visible"


def test_a_forbidden_name_is_found_in_any_capitalisation(tmp_path: Path) -> None:
    """A name is the same name however it is written; the IMPRINT values keep exact case."""
    repo = _repo(tmp_path, "see FORBIDDEN-ZONE-4711.EXAMPLE for details\n")
    assert legal.in_repository(FORBIDDEN[0], cwd=repo, ignore_case=True) is True
    assert legal.in_repository(FORBIDDEN[0], cwd=repo) is False


@pytest.mark.parametrize("workflow", ["deploy.yml", "health.yml"])
def test_every_legal_build_receives_the_secret(workflow: str) -> None:
    """A guard whose input never arrives passes on an empty list, forever."""
    import yaml  # noqa: PLC0415

    root = Path(__file__).resolve().parents[2]
    doc = yaml.safe_load((root / ".github" / "workflows" / workflow).read_text(encoding="utf-8"))
    steps = [s for job in doc["jobs"].values() for s in job.get("steps", [])]
    builds = [s for s in steps if "--legal-values-from-env" in str(s.get("run", ""))]
    assert builds, f"empty-set control: {workflow} must build with legal values"
    for step in builds:
        assert step["env"]["FORBIDDEN_STRINGS"] == "${{ secrets.FORBIDDEN_STRINGS }}"
