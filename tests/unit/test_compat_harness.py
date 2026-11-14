"""The /compat harness, driven against fake adapters (compat/harness, docs/07 §8).

Each outcome is made to happen and watched, including a hang and a crash, because a harness that
cannot report `crashes` reads a dead adapter as a quiet one. The corpus rules are held against the
real manifest, with named files, so an empty corpus cannot pass them.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import textwrap
import urllib.error
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "compat"))

import harness  # noqa: E402
from harness import check, compare, fetch, merge, runner, scope  # noqa: E402

from loremfile import config as site_config  # noqa: E402

CONFIG = scope.load_config()
MANIFEST = scope.load_manifest()

#: One adapter whose behaviour is the reader id it is asked for.
FAKE = textwrap.dedent(
    """
    import json, sys, time
    reader_id, path = sys.argv[1], sys.argv[2]
    kind = reader_id.split("/", 1)[1]
    if kind == "reads":
        print(json.dumps({"outcome": "reads", "props": {"entries": 3}}))
    elif kind == "echo":
        data = open(path, "rb").read()
        print(json.dumps({"outcome": "reads", "props": {"entries": len(data)}}))
    elif kind == "blind":
        print(json.dumps({"outcome": "reads", "props": {"entries": 3}}))
    elif kind == "refuses":
        print(json.dumps({"outcome": "refuses", "error_type": "E", "error": "no\\nsecond line"}))
    elif kind == "no-reader":
        print(json.dumps({"outcome": "no-reader"}))
    elif kind == "hang":
        time.sleep(60)
    elif kind == "crash":
        sys.stderr.write("boom\\n"); sys.exit(3)
    elif kind == "garbage":
        print("hello")
    elif kind == "two":
        print(json.dumps({"outcome": "reads", "props": {}}))
        print(json.dumps({"outcome": "reads", "props": {}}))
    elif kind == "outside":
        print(json.dumps({"outcome": "fails"}))
    elif kind == "noprops":
        print(json.dumps({"outcome": "reads"}))
    """
)


@pytest.fixture
def adapter(tmp_path: Path) -> list[str]:
    script = tmp_path / "fake.py"
    script.write_text(FAKE)
    return [sys.executable, str(script)]


def cell(command: list[str], kind: str, tmp_path: Path, timeout: float = 5) -> dict[str, Any]:
    target = tmp_path / "file.bin"
    target.write_bytes(b"abcdef")
    return runner.call(command, f"fake/{kind}", target, [], timeout, tmp_path)


# --- the adapter contract: each outcome, watched ----------------------------------------------


@pytest.mark.parametrize(
    ("kind", "outcome"),
    [
        ("reads", "reads"),
        ("refuses", "refuses"),
        ("no-reader", "no-reader"),
        ("crash", "crashes"),
        ("garbage", "crashes"),
        ("two", "crashes"),
        ("outside", "crashes"),
        ("noprops", "crashes"),
    ],
)
def test_each_outcome_the_contract_allows_or_forbids_is_seen_as_such(
    adapter: list[str], tmp_path: Path, kind: str, outcome: str
) -> None:
    assert cell(adapter, kind, tmp_path)["outcome"] == outcome


def test_an_adapter_that_hangs_is_killed_at_the_limit_and_reads_as_crashes(
    adapter: list[str], tmp_path: Path
) -> None:
    result = cell(adapter, "hang", tmp_path, timeout=1)
    assert result["outcome"] == "crashes" and "within 1 seconds" in result["detail"]


def test_a_crash_says_how_it_died(adapter: list[str], tmp_path: Path) -> None:
    detail = cell(adapter, "crash", tmp_path)["detail"]
    assert "exit status 3" in detail and "boom" in detail


def test_a_missing_adapter_is_crashes_not_an_exception(tmp_path: Path) -> None:
    result = runner.call(["/no/such/adapter"], "fake/reads", tmp_path, [], 5, tmp_path)
    assert result["outcome"] == "crashes"


# --- judging: reads, differs, the one tolerance and the one translation -----------------------


def reader(kind: str, formats: list[str] | None = None, controls: Any = None) -> dict[str, Any]:
    return {
        "id": f"python/{kind}",
        "runtime": "python",
        "formats": formats or ["zip"],
        "controls": controls or [],
    }


def file(props: dict[str, Any], target: str = "zip") -> dict[str, Any]:
    return {"path": f"{target}/x", "targets": [target], "props": props}


def test_a_property_that_agrees_reads_and_one_that_does_not_differs() -> None:
    reads = runner.judge(
        {"outcome": "reads", "props": {"entries": 3}}, file({"entries": 3}), reader("a"), CONFIG
    )
    assert reads["outcome"] == "reads" and reads["compared"] == ["entries"]
    differs = runner.judge(
        {"outcome": "reads", "props": {"entries": 2}}, file({"entries": 3}), reader("a"), CONFIG
    )
    assert differs["outcome"] == "differs"
    assert differs["differs"] == {"entries": {"reported": 2, "expected": 3}}


def test_only_names_on_both_sides_are_compared() -> None:
    cell_ = runner.judge(
        {"outcome": "reads", "props": {"entries": 3, "directories": 0}},
        file({"entries": 3}),
        reader("a"),
        CONFIG,
    )
    assert cell_["outcome"] == "reads" and cell_["compared"] == ["entries"]
    nothing = runner.judge(
        {"outcome": "reads", "props": {"entries": 9}}, file({}), reader("a"), CONFIG
    )
    assert nothing["outcome"] == "reads" and nothing["compared"] == []


def test_duration_has_a_one_millisecond_tolerance_and_nothing_else_has_any() -> None:
    tolerance = CONFIG["scope"]["tolerance"]
    assert compare.same("duration_ms", 3000, 3001, tolerance)
    assert not compare.same("duration_ms", 3000, 3002, tolerance)
    assert not compare.same("width", 100, 101, tolerance)
    assert tolerance == {"duration_ms": 1}


def test_a_boolean_is_not_the_number_it_compares_equal_to() -> None:
    assert not compare.same("items", True, 1, {})
    assert compare.same("items", True, True, {})


def test_a_csv_readers_header_record_is_expected_and_only_when_the_manifest_says_so() -> None:
    expect = {"rows": 10, "columns": 14, "has_header": True}
    assert compare.comparable("csv", expect) == {"rows": 11, "columns": 14}
    assert compare.differences("csv", {"rows": 11, "columns": 14}, expect, {}) == {}
    assert compare.differences("csv", {"rows": 10}, expect, {}) == {
        "rows": {"reported": 10, "expected": 11}
    }
    assert compare.comparable("csv", {"rows": 10, "has_header": False}) == {"rows": 10}
    assert compare.comparable("zip", {"entries": 10, "has_header": True}) == {"entries": 10}


# --- controls: both must hold, and a miss makes the reader not-run ---------------------------


def run_with(adapter: list[str], tmp_path: Path, kinds: list[str]) -> dict[str, Any]:
    config = {
        "scope": {"timeout_seconds": 5, "tolerance": {}, "properties": {"zip": ["entries"]}},
        "readers": [
            reader(k, controls=[{"reads": "zip/a.zip", "must_not": "zero-byte"}]) for k in kinds
        ],
    }
    (tmp_path / "files" / "zip").mkdir(parents=True)
    (tmp_path / "files" / "zip" / "a.zip").write_bytes(b"abcdef")
    files = [{**file({"entries": 6}), "path": "zip/a.zip"}]
    return runner.run_runtime(config, files, tmp_path, "python", "3.0", command=adapter)


def test_a_reader_that_reads_the_file_and_not_its_empty_twin_keeps_its_cells(
    adapter: list[str], tmp_path: Path
) -> None:
    part = run_with(adapter, tmp_path, ["echo"])
    assert part["cells"]["python/echo|zip/a.zip"]["outcome"] == "reads"
    assert set(part["controls"]["python/echo"].values()) == {"ok"}
    assert set(part["controls"]["python/echo"]) == {"reads:zip/a.zip", "zero-byte:zip/a.zip"}


def test_a_relative_work_directory_still_reaches_the_files(
    adapter: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first CI run passed `--work ../compat-work`: the adapter's own working directory is
    elsewhere, so a relative path named nothing and every reader's control missed."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "w").mkdir()
    part = run_with(adapter, Path("w"), ["echo"])
    assert part["cells"]["python/echo|zip/a.zip"]["outcome"] == "reads"
    assert set(part["controls"]["python/echo"].values()) == {"ok"}


def test_a_reader_that_reports_the_same_for_an_empty_file_is_not_run(
    adapter: list[str], tmp_path: Path
) -> None:
    """The negative control: `blind` ignores its input, so its empty-file control misses."""
    part = run_with(adapter, tmp_path, ["blind"])
    assert part["controls"]["python/blind"]["zero-byte:zip/a.zip"].startswith("missed")
    assert part["cells"]["python/blind|zip/a.zip"] == {
        "outcome": "not-run",
        "detail": "a control missed",
    }


def test_a_reader_that_cannot_read_its_own_control_is_not_run(
    adapter: list[str], tmp_path: Path
) -> None:
    part = run_with(adapter, tmp_path, ["refuses"])
    assert part["controls"]["python/refuses"]["reads:zip/a.zip"].startswith("missed")
    assert part["cells"]["python/refuses|zip/a.zip"]["outcome"] == "not-run"


def test_a_runtime_that_cannot_be_set_up_reports_why_and_runs_nothing(tmp_path: Path) -> None:
    part = runner.run_runtime(CONFIG, [], tmp_path, "nonesuch", "1.0")
    assert "setup_error" in part and part["cells"] == {}


# --- fetching: hashes, retries, and what counts as failed ------------------------------------


def entry(path: str = "zip/a.zip", sha: str = "aa") -> dict[str, Any]:
    return {"path": path, "url": f"https://loremfile.dev/{path}", "sha256": sha}


def test_a_file_whose_bytes_do_not_match_is_failed_and_removed_and_not_retried(
    tmp_path: Path,
) -> None:
    calls = []

    def get(_url: str, target: Path) -> str:
        calls.append(1)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
        return "bb"

    result = fetch.fetch_one(entry(), tmp_path, get=get, sleep=lambda _s: None)
    assert result["ok"] is False and "bb" in result["reason"] and len(calls) == 1
    assert not (tmp_path / "zip" / "a.zip").exists()


def test_a_network_failure_is_retried_then_failed(tmp_path: Path) -> None:
    waits: list[float] = []

    def get(_url: str, _target: Path) -> str:
        raise urllib.error.URLError("down")

    result = fetch.fetch_one(entry(), tmp_path, get=get, sleep=waits.append)
    assert (
        result["ok"] is False
        and len(waits) == fetch.ATTEMPTS - 1
        and "URLError" in result["reason"]
    )


def test_a_file_that_matches_is_ok_and_the_fetch_is_one_at_a_time(tmp_path: Path) -> None:
    order: list[str] = []

    def get(url: str, target: Path) -> str:
        order.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
        return "aa"

    files = [entry("zip/a.zip"), entry("zip/b.zip")]
    report = fetch.fetch_all(files, tmp_path, get=get, sleep=lambda _s: None)
    assert [v["ok"] for v in report["files"].values()] == [True, True]
    assert order == [f["url"] for f in files]
    assert json.loads((tmp_path / "fetch.json").read_text())["agent"] == harness.AGENT


# --- the corpus: held to the real manifest, by name ------------------------------------------

FILES, SKIPPED = scope.corpus(MANIFEST, CONFIG)
BY_PATH = {f["path"]: f for f in FILES}


def test_the_corpus_holds_the_files_it_must_and_names_them() -> None:
    for path in (
        "zip/3-text-files.zip",
        "gz/multi-member-3.gz",
        "pem/self-signed-ed25519-cert.pem",
    ):
        assert path in BY_PATH, path
    assert {f["kind"] for f in FILES} == {"ordinary", "edge"}
    assert len(FILES) > 70


def test_aliases_deprecated_and_oversize_entries_are_left_out_and_the_last_are_listed() -> None:
    aliases = [e["path"] for e in MANIFEST["fixtures"] if e.get("generator") == "alias.copy"]
    assert "zip/sample.zip" in aliases, "control: the manifest has the alias"
    assert not set(aliases) & BY_PATH.keys()
    assert "jpg/cmyk-640x480.jpg" not in BY_PATH, "deprecated"
    assert "zip/100mb.zip" not in BY_PATH
    assert "zip/100mb.zip" in {s["path"] for s in SKIPPED}
    assert all(s["bytes"] > CONFIG["scope"]["max_bytes"] for s in SKIPPED)


def test_an_edge_file_goes_to_the_readers_of_what_it_means_to_be_and_what_else_it_is() -> None:
    assert BY_PATH["edge/gif-zip-polyglot.gif"]["targets"] == ["gif", "zip"]
    assert BY_PATH["edge/pdf-zip-polyglot.pdf"]["targets"] == ["zip"]
    assert BY_PATH["edge/png-with-pdf-extension.pdf"]["targets"] == ["png"]
    assert "edge/mp4-truncated-50pct.mp4" not in BY_PATH
    assert "edge/pdf-truncated-60pct.pdf" not in BY_PATH
    ids = {r["id"] for r in scope.readers_for(BY_PATH["edge/gif-zip-polyglot.gif"], CONFIG)}
    assert {"go/image/gif", "go/archive/zip", "python/zipfile"} <= ids
    assert "python/json" not in ids


def test_the_password_and_the_delimiter_come_from_the_manifest() -> None:
    assert BY_PATH["zip/aes256-password-loremfile.zip"]["password"] == "loremfile"  # noqa: S105
    assert BY_PATH["zip/3-text-files.zip"]["password"] is None
    assert BY_PATH["csv/people-10-semicolon.csv"]["delimiter"] == ";"
    assert runner.flags_for(BY_PATH["csv/people-10-semicolon.csv"]) == ["--delimiter", ";"]


def test_every_format_in_scope_has_a_reader_or_a_stated_absence_in_each_runtime() -> None:
    for runtime in {r["runtime"] for r in CONFIG["readers"]}:
        have = {f for r in CONFIG["readers"] if r["runtime"] == runtime for f in r["formats"]}
        absent = set(CONFIG["no_reader"][runtime])
        assert have | absent == set(CONFIG["scope"]["formats"]), runtime
        assert not have & absent, runtime


def test_every_readers_control_files_are_in_the_corpus_and_every_reader_has_two() -> None:
    for reader_ in CONFIG["readers"]:
        assert reader_["controls"], reader_["id"]
        for control in reader_["controls"]:
            assert control["reads"] in BY_PATH, (reader_["id"], control["reads"])
            assert control["must_not"] in ("zero-byte", "truncated")
            fmt = BY_PATH[control["reads"]]["targets"][0]
            assert fmt in reader_["formats"], (reader_["id"], fmt)
            routed = {r["id"] for r in scope.readers_for(BY_PATH[control["reads"]], CONFIG)}
            assert reader_["id"] in routed, f"{reader_['id']} is never given its own control"


# --- merging: partial runs do not publish ----------------------------------------------------


def parts_for(files: list[dict[str, Any]], runtimes: list[tuple[str, str]]) -> list[dict[str, Any]]:
    out = []
    for runtime, version in runtimes:
        cells = {}
        for f in files:
            for r in scope.readers_for(f, CONFIG):
                if r["runtime"] == runtime:
                    cells[f"{r['id']}|{f['path']}"] = {
                        "outcome": "reads",
                        "props": {},
                        "compared": [],
                    }
        out.append(
            {
                "runtime": runtime,
                "version": version,
                "resolved": f"{version}.0",
                "cells": cells,
                "controls": {},
            }
        )
    return out


def report(failed: set[str]) -> dict[str, Any]:
    return {
        "files": {
            f["path"]: ({"ok": False, "reason": "boom"} if f["path"] in failed else {"ok": True})
            for f in FILES
        }
    }


def test_a_run_that_failed_on_more_than_three_files_is_not_written() -> None:
    paths = [f["path"] for f in FILES]
    with pytest.raises(merge.RunFailed):
        merge.merge(CONFIG, MANIFEST, report(set(paths[:4])), [], date="2026-11-13")
    ok = merge.merge(CONFIG, MANIFEST, report(set(paths[:3])), [], date="2026-11-13")
    assert set(ok["_run"]["failed_files"]) == set(paths[:3]), "three is the most a run may fail on"


def test_a_failed_file_is_not_run_in_every_cell_and_a_missing_runtime_part_is_not_run() -> None:
    path = "zip/3-text-files.zip"
    versions = merge.runtime_versions(CONFIG)
    parts = parts_for(FILES, [rv for rv in versions if rv != ("go", "1.27")])
    documents = merge.merge(CONFIG, MANIFEST, report({path}), parts, date="2026-11-13")
    row = next(r for r in documents["zip"]["files"] if r["path"] == path)
    assert {c["outcome"] for per in row["cells"].values() for c in per.values()} == {"not-run"}
    other = next(r for r in documents["zip"]["files"] if r["path"] == "zip/1mb.zip")
    assert other["cells"]["go/archive/zip"]["go-1.27"]["outcome"] == "not-run"
    assert other["cells"]["go/archive/zip"]["go-1.26"]["outcome"] == "reads"
    assert documents["_run"]["runtimes"]["go-1.27"]["resolved"] is None


def test_the_merged_results_hold_up_and_a_corrupted_one_is_caught(tmp_path: Path) -> None:
    parts = parts_for(FILES, merge.runtime_versions(CONFIG))
    documents = merge.merge(CONFIG, MANIFEST, report(set()), parts, date="2026-11-13")
    merge.write(documents, tmp_path)
    assert check.problems(tmp_path, CONFIG, MANIFEST) == []
    bad = json.loads((tmp_path / "zip.json").read_text())
    bad["files"][0]["cells"]["go/archive/zip"]["go-1.26"]["outcome"] = "fails"
    del bad["files"][1]["cells"]["python/zipfile"]["python-3.12"]
    (tmp_path / "zip.json").write_text(json.dumps(bad))
    (tmp_path / "gz.json").unlink()
    problems = check.problems(tmp_path, CONFIG, MANIFEST)
    assert any("vocabulary" in p for p in problems)
    assert any("no cell" in p for p in problems)
    assert any("gz.json: missing" in p for p in problems)


def test_results_are_sorted_and_carry_no_timestamp_outside_the_run_file() -> None:
    parts = parts_for(FILES, merge.runtime_versions(CONFIG))
    documents = merge.merge(CONFIG, MANIFEST, report(set()), parts, date="2026-11-13")
    text = merge.render(documents["zip"])
    assert text == merge.render(json.loads(text)), "keys sorted, so a re-render is the same bytes"
    assert not re.search(r"\d{4}-\d{2}-\d{2}T|\"date\"", text)
    assert documents["_run"]["date"] == "2026-11-13"


# --- isolation, the agent and the workflow ---------------------------------------------------


def test_the_agent_is_one_string_in_two_places() -> None:
    assert harness.AGENT == site_config.COMPAT_USER_AGENT
    assert harness.AGENT.startswith("loremfile-compat/")


def test_nothing_in_compat_imports_the_repository() -> None:
    sources = sorted((ROOT / "compat").rglob("*.py"))
    assert len(sources) >= 8, "control: the finder found the harness and the adapter"
    importing = re.compile(r"^\s*(?:from|import)\s+(?:loremfile|src)\b", re.M)
    assert [p for p in sources if importing.search(p.read_text())] == []
    # And the control: the pattern does catch an import.
    assert importing.search("import loremfile.site\n") and importing.search(
        "from loremfile import x\n"
    )


def workflow() -> dict[str, Any]:
    return yaml.safe_load((ROOT / ".github" / "workflows" / "compat.yml").read_text())


def test_the_workflow_runs_the_versions_runtimes_yaml_names_and_is_never_required() -> None:
    jobs = workflow()["jobs"]
    for runtime in CONFIG["runtime_list"]:
        matrix = jobs[runtime["id"]]["strategy"]["matrix"]["version"]
        assert matrix == runtime["versions"], runtime["id"]
        assert jobs[runtime["id"]]["continue-on-error"] is True
    triggers = workflow()[True]  # YAML reads the key `on` as a boolean
    assert set(triggers) == {"workflow_dispatch", "pull_request", "schedule"}
    cron = triggers["schedule"][0]["cron"].split()
    assert cron[2] == "1" and cron[3:] == ["*", "*"], "monthly: the first day of the month"
    assert triggers["pull_request"]["paths"] == ["compat/**", "!compat/results/**"]
    text = (ROOT / ".github" / "workflows" / "compat.yml").read_text()
    for forbidden in ("TOOLCHAIN", "needs.setup", "ghcr.io", "container:", "src/loremfile"):
        assert forbidden not in text, f"compat.yml must stay clear of the toolchain: {forbidden}"
    sample = "    container: x"
    assert "container:" in sample, "control: the check would see a container"


def test_every_runtime_names_the_page_that_lists_its_versions_and_the_date() -> None:
    for runtime in CONFIG["runtime_list"]:
        runtimes = yaml.safe_load((ROOT / "compat" / "runtimes.yaml").read_text())
        found = next(r for r in runtimes["runtimes"] if r["id"] == runtime["id"])
        assert found["source"].startswith("https://") and found["versions"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", CONFIG["checked"])


# --- the named exceptions ---------------------------------------------------------------------

NAMESPACED = (
    '<?xml version="1.0"?>\n<catalogue xmlns="https://loremfile.dev/ns/catalogue" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>x</dc:title></catalogue>\n'
)


def load_python_adapter() -> Any:
    spec = importlib.util.spec_from_file_location(
        "compat_python_adapter", ROOT / "compat" / "adapters" / "python" / "adapter.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_exceptions_are_named_in_readers_yaml_beside_the_tolerance() -> None:
    exceptions = {e["name"]: e for e in CONFIG["scope"]["exceptions"]}
    assert set(exceptions) == {"Duration", "CSV header", "Clark notation", "Name strings"}
    assert f"{CONFIG['scope']['tolerance']['duration_ms']} ms" in exceptions["Duration"]["text"]
    ids = {r["id"] for r in CONFIG["readers"]}
    for exception in exceptions.values():
        assert exception["applies"] and set(exception["applies"]) <= ids, exception["name"]


def test_a_root_in_clark_notation_is_reported_as_its_local_name_and_namespace_apart(
    tmp_path: Path,
) -> None:
    adapter = load_python_adapter()
    plain, spaced = tmp_path / "plain.xml", tmp_path / "spaced.xml"
    plain.write_text("<people><p/></people>")
    spaced.write_text(NAMESPACED)
    for reader_id in ("python/xml.etree.ElementTree", "python/xml.dom.minidom"):
        found = adapter.answer(reader_id, str(spaced), None, None)["props"]
        assert found == {
            "root_element": "catalogue",
            "root_namespace": "https://loremfile.dev/ns/catalogue",
        }, reader_id
        assert adapter.answer(reader_id, str(plain), None, None)["props"] == {
            "root_element": "people"
        }, reader_id
    # Control: the library's own spelling is the one being reduced, so the reduction does work.
    own = ElementTree.parse(spaced).getroot().tag  # noqa: S314 - our own test file
    assert own == "{https://loremfile.dev/ns/catalogue}catalogue"


def test_a_namespace_is_never_compared_and_so_never_reads_as_a_difference() -> None:
    expect = {"root_element": "catalogue"}
    reported = {"root_element": "catalogue", "root_namespace": "https://loremfile.dev/ns/catalogue"}
    assert compare.differences("xml", reported, expect, {}) == {}
    assert compare.compared("xml", reported, expect) == ["root_element"]
    assert compare.differences("xml", {"root_element": "{x}catalogue"}, expect, {}) != {}


# --- routing: a reader that does not decompress is not handed a compressed file ----------------


def routed(path: str) -> set[str]:
    return {r["id"] for r in scope.readers_for(BY_PATH[path], CONFIG)}


def test_a_reader_that_takes_uncompressed_tar_is_not_given_a_compressed_one() -> None:
    assert routed("tar/3-text-files.tar") == {
        "go/archive/tar",
        "python/tarfile",
        "ruby/Gem::Package::TarReader",
    }
    assert routed("tar/3-text-files.tar.gz") == {
        "go/archive/tar+compress/gzip",
        "python/tarfile",
        "ruby/Gem::Package::TarReader+Zlib::GzipReader",
    }
    assert routed("tar/3-text-files.tar.xz") == {"python/tarfile"}
    assert BY_PATH["tar/3-text-files.tar.gz"]["route"] == {"compression": "gz"}
    assert BY_PATH["tar/3-text-files.tar"]["route"] == {"compression": ""}, "plain tar says so"


def test_go_and_ruby_have_no_reader_for_xz_tar_and_only_for_that_file() -> None:
    assert scope.no_reader_for(BY_PATH["tar/3-text-files.tar.xz"], CONFIG) == ["go", "ruby"]
    assert scope.no_reader_for(BY_PATH["tar/3-text-files.tar.gz"], CONFIG) == []
    assert scope.no_reader_for(BY_PATH["zip/3-text-files.zip"], CONFIG) == []


def test_routing_matches_on_the_files_manifest_props_and_a_file_without_one_matches_none() -> None:
    plain = {"route": {"compression": ""}}
    assert scope.matches(plain, {"compression": [""]})
    assert not scope.matches(plain, {"compression": ["gz"]})
    assert not scope.matches({"route": {"compression": None}}, {"compression": [""]})
    assert scope.matches({"route": {}}, {})


def test_the_routing_text_names_readers_that_exist() -> None:
    ids = {r["id"] for r in CONFIG["readers"]}
    for entry in CONFIG["scope"]["routing"]:
        assert entry["format"] in CONFIG["scope"]["formats"] and set(entry["applies"]) <= ids


# --- the adapters and the reader list agree, and every absence says why --------------------------


def test_every_reader_id_is_a_string_in_its_runtimes_adapter() -> None:
    adapters = {r["id"]: ROOT / "compat" / r["adapter"] for r in CONFIG["runtime_list"]}
    assert len(adapters) == 5, "control: Python, Go, Node.js, Java and Ruby"
    for reader_ in CONFIG["readers"]:
        source = adapters[reader_["runtime"]].read_text(encoding="utf-8")
        assert f'"{reader_["id"]}"' in source or f"'{reader_['id']}'" in source, reader_["id"]
    registered = {r["id"] for r in CONFIG["readers"] if r["runtime"] == "ruby"}
    assert "ruby/Zlib::GzipReader" in registered, (
        "control: ids with colons and plus signs are found"
    )


def test_every_absence_has_a_reason_and_the_ones_the_owner_named_are_there() -> None:
    for runtime, formats in CONFIG["no_reader"].items():
        for fmt, reason in formats.items():
            assert reason.strip() and fmt in CONFIG["scope"]["formats"], (runtime, fmt)
    assert {"tar", "json", "csv"} == set(CONFIG["no_reader"]["java"])
    assert {"zip", "csv", "xml", "wav", "jpg", "png", "gif"} <= set(CONFIG["no_reader"]["node"])


def test_nothing_in_any_adapter_reaches_into_the_repository() -> None:
    kinds = {".py", ".go", ".mjs", ".java", ".rb"}
    sources = [p for p in (ROOT / "compat" / "adapters").rglob("*") if p.suffix in kinds]
    assert {p.suffix for p in sources} >= {".py", ".go", ".mjs", ".java", ".rb"}, "control"
    for path in sources:
        assert "src/loremfile" not in path.read_text(encoding="utf-8"), path
