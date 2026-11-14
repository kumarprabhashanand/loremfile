"""One guessable URL per format: `/{format}/sample.{format}` (docs/05 §8, catalogue 1.15.0).

An alias is a new permanent path with the bytes of the file a format's page starts with. What has
to hold: it equals its original byte for byte, it never names a file that only the CI reference
fleet reproduces, `sample` is nobody else's name, and the site never counts it as a second file.
Each guard is shown firing on a broken copy.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from catalog_helpers import minimal_fixture

from loremfile.build import load_generators
from loremfile.catalog import ALIAS_STEM, Catalog, CatalogError, Fixture, make_alias
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.manifest import Manifest, alias_original, is_alias
from loremfile.site import build, defaults, routes
from loremfile.util.determinism import deterministic
from loremfile.validators import load, validate

ROOT = Path(__file__).resolve().parents[2]
WHEN = dt.datetime(2026, 9, 15, 12, 0, tzinfo=dt.UTC)
CATALOG = Catalog.load()
MANIFEST = json.loads((ROOT / "manifest.json").read_text())["fixtures"]
BY_PATH = {e["path"]: e for e in MANIFEST}
ALIASES = yaml.safe_load((ROOT / "catalog" / "_aliases.yaml").read_text())["aliases"]
FAMILY = {f.format: f.family.value for f in CATALOG.formats}
DRIFTING = {f.path for fmt in CATALOG.formats for f in fmt.fixtures if f.expected_drift}
NO_ALIAS = {"edge", "hls", "opus"}
load_generators()
load()


def loaded_with(tmp_path: Path, aliases: dict[str, str]) -> Catalog:
    """The real catalog, with `_aliases.yaml` replaced: a way to ask the loader what it refuses."""
    copy = tmp_path / "catalog"
    shutil.copytree(ROOT / "catalog", copy)
    (copy / "_aliases.yaml").write_text(yaml.safe_dump({"aliases": aliases}), encoding="utf-8")
    return Catalog.load(copy)


def disagreements(entries: list[dict[str, Any]]) -> list[str]:
    """Every alias entry that differs from its original in bytes, hash, type or props."""
    by_path = {e["path"]: e for e in entries}
    keys = ("sha256", "bytes", "mime", "props")
    return [
        e["path"]
        for e in entries
        if is_alias(e)
        and tuple(e[k] for k in keys) != tuple(by_path[alias_original(e)][k] for k in keys)
    ]


# --- which files, and what they are -----------------------------------------------------------


def test_the_aliases_are_found_where_they_are_known_to_be() -> None:
    """Empty-set control: every check below holds of nothing if no alias exists."""
    assert len(ALIASES) == 77 and ALIASES["pdf"] == "pdf/a4-3pages.pdf"
    assert ALIASES["webm"] == "webm/720p-5s-vp8.webm" and ALIASES["gif"] == "gif/static-256x256.gif"
    aliases = [e for e in MANIFEST if is_alias(e)]
    assert len(aliases) == 77 and "pdf/sample.pdf" in {e["path"] for e in aliases}
    assert ALIASES["ogv"] == "ogv/720p-5s.ogv" and ALIASES["ts"] == "ts/720p-5s.ts"
    assert set(FAMILY) - set(ALIASES) == NO_ALIAS, "hls, edge and opus have none"


def test_the_mapping_is_what_the_default_rule_chooses_today() -> None:
    """A row is permanent once published, so this fails when the rule would now pick another
    file, and asks for a decision instead of moving the alias."""
    ruled = {}
    for fmt, family in FAMILY.items():
        found = defaults.default_choice(fmt, family, MANIFEST, DRIFTING, build.POPULAR)
        if found:
            ruled[fmt] = found[0]
    assert ruled == ALIASES
    assert all(path.rsplit(".", 1)[1] == fmt for fmt, path in ALIASES.items()), "the ext is the key"


def test_the_alias_rows_the_loader_makes_are_the_originals_with_a_new_name() -> None:
    for fmt, target in ALIASES.items():
        alias, original = CATALOG.by_path[f"{fmt}/sample.{fmt}"], CATALOG.by_path[target]
        assert alias.alias_of == target and alias.depends_on == [target]
        assert alias.generator == "alias.copy" and alias.params == {"of": target}
        assert (alias.expect, alias.mime, alias.contains_text) == (
            original.expect,
            original.mime,
            original.contains_text,
        ), "checked by the same expect, so nothing is copied by hand"
        assert alias.phase == 2 and alias.size_class.value == "free" and original.alias_of is None


# --- equal bytes -------------------------------------------------------------------------------


def test_every_alias_has_the_sha256_and_everything_else_of_its_original() -> None:
    aliases = [e for e in MANIFEST if is_alias(e)]
    assert disagreements(MANIFEST) == [] and len(aliases) == 77
    for e in aliases:
        assert e["path"] == f"{e['format']}/sample.{e['format']}"
        assert not is_alias(BY_PATH[alias_original(e)])
        assert e["generator_params"] == {"of": alias_original(e)}
        assert "aliasOf" not in e, "the published schema has no such field (docs/04 §1.4)"
    sums = {
        path: sha
        for sha, path in (
            line.split("  ", 1) for line in (ROOT / "sha256sums.txt").read_text().splitlines()
        )
    }
    assert all(sums[e["path"]] == sums[alias_original(e)] for e in aliases), "sha256sums.txt too"


def test_a_hash_that_differs_is_what_the_comparison_catches() -> None:
    broken = [dict(e) for e in MANIFEST]
    target = next(e for e in broken if e["path"] == "csv/sample.csv")
    target["sha256"] = target["sha256"][:-1] + ("0" if target["sha256"][-1] != "0" else "1")
    assert disagreements(broken) == ["csv/sample.csv"]
    other = next(e for e in broken if e["path"] == "json/sample.json")
    other["bytes"] += 1
    assert disagreements(broken) == ["csv/sample.csv", "json/sample.json"]


def test_the_generator_reads_the_original_and_changes_nothing(tmp_path: Path) -> None:
    context = GeneratorContext(path="pdf/sample.pdf", workdir=tmp_path)
    context._dependency = lambda path: f"bytes of {path}".encode()  # type: ignore[assignment]
    with deterministic(context.seed):
        assert REGISTRY.get("alias.copy")(context, of="pdf/a4-3pages.pdf") == (
            b"bytes of pdf/a4-3pages.pdf"
        )


def test_a_bin_alias_is_held_to_its_originals_seed_and_a_stranger_is_not(tmp_path: Path) -> None:
    original = CATALOG.by_path["bin/10mib-plus-1.bin"]
    context = GeneratorContext(path=original.path, workdir=tmp_path)
    with deterministic(context.seed):
        data = REGISTRY.get(original.generator)(context, **original.params)
    alias = CATALOG.by_path["bin/sample.bin"]
    assert validate(data, alias, CATALOG.mime_for(alias)).ok
    stranger = original.model_copy(update={"name": "other.bin"})
    refused = validate(data, stranger, CATALOG.mime_for(stranger))
    assert not refused.ok and "own seed" in " ".join(refused.failures), "control"


# --- what may not be aliased, and what may not be called sample --------------------------------


def test_no_alias_names_a_file_only_the_ci_fleet_reproduces() -> None:
    assert len(DRIFTING) == 11, "control: the exclusion has something to exclude"
    assert not {alias_original(e) for e in MANIFEST if is_alias(e)} & DRIFTING
    assert not set(ALIASES.values()) & DRIFTING
    assert {p.split("/")[0] for p in DRIFTING} >= {"mp4", "webm", "mkv", "opus"}


def test_the_loader_refuses_to_alias_a_drifting_edge_superseded_or_unknown_file(tmp_path) -> None:
    for fmt, target, why in (
        ("opus", "opus/30s.opus", "expected_drift"),
        ("mp4", "mp4/1080p-60s.mp4", "expected_drift"),
        ("jpg", "jpg/cmyk-640x480.jpg", "not an ordinary, current file"),
        ("pdf", "pdf/no-such-file.pdf", "is not a fixture of pdf"),
        ("nosuch", "pdf/a4-3pages.pdf", "not a catalogued format"),
    ):
        with pytest.raises(CatalogError, match=why):
            loaded_with(tmp_path / fmt, {**ALIASES, fmt: target})
    # Control: the real mapping loads, and so does one with an ordinary file in place of pdf's.
    assert loaded_with(tmp_path / "ok", ALIASES).by_path["pdf/sample.pdf"].alias_of
    other = loaded_with(tmp_path / "other", {**ALIASES, "pdf": "pdf/minimal.pdf"})
    assert other.by_path["pdf/sample.pdf"].alias_of == "pdf/minimal.pdf"


def test_sample_is_reserved_for_the_alias_and_cannot_be_a_format() -> None:
    assert "sample" in build.RESERVED and ALIAS_STEM == "sample"
    with pytest.raises(ValueError, match="reserved"):
        Fixture(**minimal_fixture(name="sample.pdf", format="pdf"))
    alias = make_alias(CATALOG.by_path["pdf/a4-3pages.pdf"])
    assert alias.path == "pdf/sample.pdf", "control: the alias itself is fine"
    with pytest.raises(ValueError, match=r"named sample\.pdf"):
        alias.model_validate({**alias.model_dump(), "name": "sample.pdfx"})
    with pytest.raises(ValueError, match="none of superseded"):
        alias.model_validate({**alias.model_dump(), "edge_case": True})


# --- the site ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("aliases") / "site"
    build.build(out, root=ROOT, committed=WHEN)
    return out


def test_the_counts_leave_aliases_out(site: Path) -> None:
    manifest = Manifest.load()
    files = len(manifest.current)
    assert files == len([e for e in MANIFEST if not is_alias(e) and not e.get("supersededBy")])
    assert len(manifest.active) == len(MANIFEST) == files + 77 + 1, "77 aliases, 1 superseded"
    home = (site / "index.html").read_text(encoding="utf-8")
    assert f"Search {files} files by path or description" in home
    counts = [int(n) for n in re.findall(r'<span class="count">(\d+)</span>', home)]
    assert sum(counts) == files, "the format grid"
    pdf = (site / "pdf.html").read_text(encoding="utf-8")
    assert "20 files." in pdf and "sample.pdf" not in pdf.split("<tbody>", 1)[1]
    search = json.loads((site / "search-index.json").read_text(encoding="utf-8"))
    assert len(search) == files and not [r for r in search if "/sample." in r["path"]]
    index = json.loads((site / routes.format_index_key("pdf")).read_text(encoding="utf-8"))
    assert index["count"] == 20 and "pdf/sample.pdf" not in {e["path"] for e in index["fixtures"]}
    formats = json.loads((ROOT / "formats.json").read_text(encoding="utf-8"))["formats"]
    assert sum(f["count"] for f in formats) == len(MANIFEST) - 77, "formats.json: no aliases"
    llms = (site / "llms-full.txt").read_text(encoding="utf-8")
    assert not re.search(r"^\| [a-z0-9]+/sample\.[a-z0-9]+ \|", llms, re.MULTILINE)
    assert "| pdf/a4-3pages.pdf |" in llms, "control: the table lists the originals"


def test_the_manifest_and_the_checksums_do_carry_them() -> None:
    document = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert document["count"] == len(MANIFEST) and "pdf/sample.pdf" in BY_PATH
    assert "pdf/sample.pdf" in (ROOT / "sha256sums.txt").read_text(encoding="utf-8")


def test_a_format_page_starts_with_its_alias_and_says_whose_bytes_it_is(site: Path) -> None:
    for fmt, target in ALIASES.items():
        html = (site / f"{fmt}.html").read_text(encoding="utf-8")
        block = html.split('<section class="start"', 1)[1].split("</section>", 1)[0]
        assert f"<code>https://loremfile.dev/{fmt}/sample.{fmt}</code>" in block, fmt
        assert f'href="/{fmt}/sample.{fmt}" download' in block, fmt
        assert f"<code>{target}</code>" in block, fmt
    for fmt in NO_ALIAS:
        assert 'class="start"' not in (site / f"{fmt}.html").read_text(encoding="utf-8"), fmt


def test_the_home_example_and_the_rule_in_llms_and_the_naming_page(site: Path) -> None:
    home = (site / "index.html").read_text(encoding="utf-8")
    assert "<code>https://loremfile.dev/pdf/sample.pdf</code>" in home
    llms = (site / "llms.txt").read_text(encoding="utf-8")
    line = next(row for row in llms.splitlines() if "{format}/sample.{format}" in row)
    assert "pdf/sample.pdf" in line and all(fmt in line for fmt in NO_ALIAS), line
    naming = (site / "docs/naming.html").read_text(encoding="utf-8")
    sentence = naming.split("Is there a name I can guess?", 1)[1].split("</p>", 1)[0]
    assert "/{format}/sample.{format}" in sentence and all(f in sentence for f in NO_ALIAS)


def test_the_docs_table_and_the_mapping_agree() -> None:
    text = (ROOT / "docs" / "05-fixture-catalog.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| `([a-z0-9]+)` \| `([^`]+)` \| ([^|]+) \|$", text, re.MULTILINE)
    assert {fmt: path for fmt, path, _ in rows} == ALIASES
    assert "catalog/_aliases.yaml" in text and "equal SHA-256" in text
