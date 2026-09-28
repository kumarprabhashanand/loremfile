"""`get`, `list` and `verify` against the loopback server (conftest.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from loremfile_client import api, cli

from conftest import BODIES, Handler


def run(*argv: str) -> int:
    return cli.main(list(argv))


def test_get_writes_the_files_it_verified(server: str, dest: Path) -> None:
    assert run("get", "pdf/small.pdf", "txt/notes.txt", "--dest", str(dest)) == cli.OK
    assert (dest / "pdf" / "small.pdf").read_bytes() == BODIES["pdf/small.pdf"]
    assert (dest / "txt" / "notes.txt").read_bytes() == BODIES["txt/notes.txt"]


def test_get_by_format_takes_every_file_of_it(server: str, dest: Path) -> None:
    assert run("get", "--format", "pdf", "--dest", str(dest)) == cli.OK
    assert sorted(p.name for p in (dest / "pdf").iterdir()) == ["other.pdf", "small.pdf"]


def test_a_withdrawn_entry_is_not_offered(server: str, dest: Path) -> None:
    assert run("get", "pdf/withdrawn.pdf", "--dest", str(dest)) == cli.REFUSED


def test_bytes_that_do_not_match_are_not_written(server: str, dest: Path) -> None:
    """The reason the package exists: a file that fails its hash must not reach the disk,
    and the command must not report success."""
    Handler.corrupt = {"pdf/small.pdf"}
    assert run("get", "pdf/small.pdf", "--dest", str(dest)) == cli.FAILED
    assert not (dest / "pdf" / "small.pdf").exists()


def test_an_unknown_path_is_refused_before_anything_is_fetched(server: str, dest: Path) -> None:
    assert run("get", "pdf/not-real.pdf", "--dest", str(dest)) == cli.REFUSED
    assert not dest.exists()


def test_naming_nothing_is_refused(server: str, dest: Path) -> None:
    assert run("get", "--dest", str(dest)) == cli.REFUSED


def test_a_catalog_version_that_has_moved_on_is_refused(server: str, dest: Path) -> None:
    assert (
        run("get", "pdf/small.pdf", "--dest", str(dest), "--catalog-version", "1.0.0")
        == cli.REFUSED
    )
    assert run("get", "pdf/small.pdf", "--dest", str(dest), "--catalog-version", "9.9.9") == cli.OK


def test_an_existing_file_is_kept_unless_force(server: str, dest: Path) -> None:
    assert run("get", "pdf/small.pdf", "--dest", str(dest)) == cli.OK
    (dest / "pdf" / "small.pdf").write_bytes(b"mine")
    assert run("get", "pdf/small.pdf", "--dest", str(dest)) == cli.OK
    assert (dest / "pdf" / "small.pdf").read_bytes() == b"mine", "it overwrote without --force"
    assert run("get", "pdf/small.pdf", "--dest", str(dest), "--force") == cli.OK
    assert (dest / "pdf" / "small.pdf").read_bytes() == BODIES["pdf/small.pdf"]


def test_a_dry_run_fetches_nothing(server: str, dest: Path, capsys: pytest.CaptureFixture) -> None:
    assert run("get", "--format", "pdf", "--dest", str(dest), "--dry-run", "--json") == cli.OK
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["files"] == 2
    assert report["summary"]["bytes"] == sum(
        len(BODIES[p]) for p in ("pdf/small.pdf", "pdf/other.pdf")
    )
    assert not dest.exists()


def test_list_filters_without_downloading(server: str, capsys: pytest.CaptureFixture) -> None:
    assert run("list", "--format", "pdf", "--json") == cli.OK
    assert {item["path"] for item in json.loads(capsys.readouterr().out)["items"]} == {
        "pdf/small.pdf",
        "pdf/other.pdf",
    }
    assert run("list", "--max-bytes", "13", "--json") == cli.OK
    listed = {item["path"] for item in json.loads(capsys.readouterr().out)["items"]}
    assert listed == {"txt/notes.txt"}, listed


def test_verify_reports_missing_and_changed_files(server: str, dest: Path) -> None:
    assert run("get", "--format", "pdf", "--dest", str(dest)) == cli.OK
    assert run("verify", "--dest", str(dest)) == cli.OK

    (dest / "pdf" / "small.pdf").write_bytes(b"not what was published")
    assert run("verify", "--dest", str(dest)) == cli.FAILED

    (dest / "pdf" / "small.pdf").unlink()
    assert run("verify", "pdf/small.pdf", "--dest", str(dest)) == cli.FAILED


def test_verify_on_an_empty_directory_checks_nothing_and_says_so(
    server: str, dest: Path, capsys: pytest.CaptureFixture
) -> None:
    """A verify that finds no files must not report success over an empty set silently."""
    dest.mkdir(parents=True)
    assert run("verify", "--dest", str(dest), "--json") == cli.OK
    assert json.loads(capsys.readouterr().out)["summary"] == {"checked": 0, "failing": 0}


def test_a_host_that_is_not_answering_is_a_separate_exit_code(
    monkeypatch: pytest.MonkeyPatch, dest: Path
) -> None:
    """Told apart from a verification failure on purpose: one is a broken network, the
    other is a broken file, and a script should be able to retry only the first."""
    monkeypatch.setenv(api.OVERRIDE, "http://127.0.0.1:1/")
    assert run("get", "pdf/small.pdf", "--dest", str(dest)) == cli.UNREACHABLE


def test_a_fixture_path_that_would_escape_the_destination_is_refused(dest: Path) -> None:
    with pytest.raises(api.Refused, match="not the shape of a fixture path"):
        api.target(dest, "../elsewhere.txt")
    with pytest.raises(api.Refused, match="not the shape of a fixture path"):
        api.target(dest, "/etc/passwd")
