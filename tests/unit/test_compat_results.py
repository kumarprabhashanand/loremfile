"""The committed results of /compat (compat/results, docs/07 §8).

Written by the workflow, never by hand; this holds that what is committed is whole: every
in-scope file and reader pair has a cell, every path is in the manifest with its bytes, and the
vocabulary is closed. Named specifics, not counts, are the controls that the files were read at
all, so a results directory that came back empty cannot pass.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "compat"))

from harness import OUTCOMES, check, merge, scope  # noqa: E402

CONFIG = scope.load_config()
MANIFEST = scope.load_manifest()
RESULTS = ROOT / "compat" / "results"
FORMATS = CONFIG["scope"]["formats"]


def document(fmt: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((RESULTS / f"{fmt}.json").read_text(encoding="utf-8"))
    return loaded


def test_the_results_hold_up_against_the_manifest_and_the_reader_list() -> None:
    assert check.problems(RESULTS, CONFIG, MANIFEST) == []


def test_the_files_were_read_at_all() -> None:
    """Named specifics: an empty or truncated results directory fails here, not silently."""
    rows = {row["path"]: row for row in document("zip")["files"]}
    row = rows["zip/3-text-files.zip"]
    cell = row["cells"]["python/zipfile"]["python-3.12"]
    assert cell["outcome"] == "reads" and cell["props"]["entries"] == 3
    assert row["expect"]["entries"] == 3, "the manifest's value sits beside the reader's"
    assert "edge/zero-byte.zip" in rows and "zip/100mb.zip" in {
        s["path"] for s in document("zip")["skipped"]
    }
    assert document("pem")["no_reader"] == ["python"]
    assert document("wav")["no_reader"] == ["go"]


def test_the_vocabulary_is_closed_and_no_cell_is_outside_it() -> None:
    seen = set()
    for fmt in FORMATS:
        for row in document(fmt)["files"]:
            for per in row["cells"].values():
                seen |= {cell["outcome"] for cell in per.values()}
    assert seen <= set(OUTCOMES), seen - set(OUTCOMES)
    assert {"reads", "refuses"} <= seen, "control: the run produced both ordinary outcomes"


def test_every_format_has_a_file_and_every_reader_a_column() -> None:
    for fmt in FORMATS:
        doc = document(fmt)
        assert doc["files"], fmt
        assert [r["id"] for r in doc["readers"]] == sorted(
            r["id"] for r in CONFIG["readers"] if fmt in r["formats"]
        )


def test_the_run_record_names_a_run_a_date_and_every_runtime_version() -> None:
    run = json.loads((RESULTS / "_run.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", run["date"]) and run["run_id"].isdigit()
    assert set(run["runtimes"]) == {f"{rt}-{v}" for rt, v in merge.runtime_versions(CONFIG)}
    for key, info in run["runtimes"].items():
        assert str(info["resolved"]).startswith(key.split("-", 1)[1]), (key, info)
    assert run["failed_files"] == {}, "a run with a file that did not fetch is not committed"
    assert run["agent"].startswith("loremfile-compat/")


def test_results_are_sorted_and_carry_no_timestamp_outside_the_run_record() -> None:
    for fmt in FORMATS:
        text = (RESULTS / f"{fmt}.json").read_text(encoding="utf-8")
        assert text == merge.render(json.loads(text)), f"{fmt}.json is not in canonical form"
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d|\"date\"|\"run_id\"", text), fmt


def test_every_reader_ran_its_controls_on_every_runtime_version_it_has() -> None:
    for fmt in FORMATS:
        for reader_id, per in document(fmt)["controls"].items():
            runtime = reader_id.split("/", 1)[0]
            versions = {f"{rt}-{v}" for rt, v in merge.runtime_versions(CONFIG) if rt == runtime}
            assert set(per) == versions, (fmt, reader_id)
            for version, controls in per.items():
                assert len(controls) >= 2, (reader_id, version, "two controls named")


def test_the_check_fires_on_a_broken_copy(tmp_path: Path) -> None:
    """Negative control: the same checks over a copy with one cell's outcome made up and one
    whole file removed report both."""
    copy = tmp_path / "results"
    shutil.copytree(RESULTS, copy)
    broken = json.loads((copy / "gz.json").read_text(encoding="utf-8"))
    first = next(iter(broken["files"][0]["cells"].values()))
    first[next(iter(first))]["outcome"] = "fails"
    (copy / "gz.json").write_text(json.dumps(broken), encoding="utf-8")
    (copy / "der.json").unlink()
    problems = check.problems(copy, CONFIG, MANIFEST)
    assert any("gz.json" in p and "vocabulary" in p for p in problems)
    assert any("der.json: missing" in p for p in problems)


@pytest.mark.parametrize("fmt", ["csv", "xml"])
def test_the_translations_are_visible_in_the_results(fmt: str) -> None:
    """csv's rows and xml's root are the two places a reader's native value is not the
    manifest's spelling; each file row keeps the manifest's own value for the page to show."""
    rows = {row["path"]: row for row in document(fmt)["files"]}
    probe = "csv/people-10.csv" if fmt == "csv" else "xml/with-namespaces.xml"
    expected = rows[probe]["expect"]
    assert expected == (
        {"columns": 14, "has_header": True, "rows": 10}
        if fmt == "csv"
        else {"root_element": "catalogue"}
    )


def test_the_namespaced_file_reads_in_every_xml_reader_on_every_version() -> None:
    """The first run read ElementTree's Clark notation as five `differs`; the adapter now
    reports the local name, as the manifest and the other readers do (docs/07 §8)."""
    rows = {row["path"]: row for row in document("xml")["files"]}
    row = rows["xml/with-namespaces.xml"]
    assert row["expect"] == {"root_element": "catalogue"}
    seen = 0
    for reader_id, per in row["cells"].items():
        for version, cell in per.items():
            seen += 1
            assert cell["outcome"] == "reads", (reader_id, version, cell)
            assert cell["props"]["root_element"] == "catalogue", (reader_id, version)
            assert cell["props"]["root_namespace"] == "https://loremfile.dev/ns/catalogue"
    versions = merge.runtime_versions(CONFIG)
    expected = sum(
        1
        for reader in CONFIG["readers"]
        if "xml" in reader["formats"]
        for rt, _ in versions
        if rt == reader["runtime"]
    )
    assert seen == expected and seen > 0, "control: every xml reader and version was seen"


def test_the_tar_asymmetry_the_page_states_is_what_the_results_hold() -> None:
    """Python's tar reader decompresses and Go's does not: the sentence on /compat/tar is
    owner-requested prose, so each part of it is held to the results here."""
    rows = {row["path"]: row for row in document("tar")["files"]}
    plain, gz, xz = (rows[f"tar/3-text-files.tar{ext}"] for ext in ("", ".gz", ".xz"))

    def outcomes(row: dict[str, Any], reader: str) -> set[str]:
        return {cell["outcome"] for cell in row["cells"][reader].values()}

    for row in (plain, gz, xz):
        assert outcomes(row, "python/tarfile") == {"reads"}, row["path"]
        assert row["cells"]["python/tarfile"]["python-3.13"]["props"]["entries"] == 3
    assert set(plain["cells"]) == {"go/archive/tar", "python/tarfile"}
    assert set(gz["cells"]) == {"go/archive/tar+compress/gzip", "python/tarfile"}
    assert set(xz["cells"]) == {"python/tarfile"} and xz["no_reader"] == ["go"]
    assert outcomes(plain, "go/archive/tar") == {"reads"}
    assert outcomes(gz, "go/archive/tar+compress/gzip") == {"reads"}
    assert gz["cells"]["go/archive/tar+compress/gzip"]["go-1.27"]["props"]["entries"] == 3
    assert gz["no_reader"] == plain["no_reader"] == []
