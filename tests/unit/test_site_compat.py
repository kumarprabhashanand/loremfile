"""The /compat pages (docs/07 §8): generated from the results, every figure traceable to them."""

from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import re
from pathlib import Path

import pytest

from loremfile import config
from loremfile.site import build, compat, routes

ROOT = Path(__file__).resolve().parents[2]
WHEN = dt.datetime(2026, 9, 15, 12, 0, tzinfo=dt.UTC)
RESULTS = ROOT / "compat" / "results"
READERS = json.loads((ROOT / "compat" / "readers.yaml").read_text(encoding="utf-8"))
FORMATS = READERS["scope"]["formats"]
MAIN = re.compile(r"<main[^>]*>(.*?)</main>", re.S)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("built") / "site"
    build.build(out, root=ROOT, committed=WHEN)
    return out


def text(site: Path, key: str) -> str:
    return (site / routes.disk_path(key)).read_text(encoding="utf-8")


def main_text(html: str) -> str:
    """The words of a page's own content, with no markup, no attributes and no site chrome."""
    found = MAIN.search(html)
    assert found, "control: the page has a main region"
    return htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", found.group(1))))


def results_text() -> str:
    return " ".join(p.read_text(encoding="utf-8") for p in sorted(RESULTS.glob("*.json")))


def tallies(fmt: str) -> set[str]:
    """Counts worked out here, from the files, by a route that shares nothing with the page."""
    document = json.loads((RESULTS / f"{fmt}.json").read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    versions: set[str] = set()
    for row in document["files"]:
        for per in row["cells"].values():
            versions |= set(per)
            if row["kind"] == "ordinary":
                for cell in per.values():
                    counts[cell["outcome"]] = counts.get(cell["outcome"], 0) + 1
    found = {str(n) for n in counts.values()} | {"0"}
    found |= {str(len(document["files"])), str(len(document["readers"])), str(len(versions))}
    return found


def sizes(fmt: str) -> set[str]:
    document = json.loads((RESULTS / f"{fmt}.json").read_text(encoding="utf-8"))
    rows = [*document["files"], *document["skipped"]]
    return {n for row in rows for n in NUMBER.findall(build.sized(row["bytes"]))}


def allowed(fmt: str | None) -> set[str]:
    scope = READERS["scope"]
    figures = {str(scope["timeout_seconds"]), str(scope["max_bytes"] // 1_000_000)}
    figures |= {str(v) for v in scope["tolerance"].values()}
    pool = set(NUMBER.findall(results_text())) | figures
    for name in [fmt] if fmt else FORMATS:
        pool |= tallies(name) | sizes(name)
    return pool


def unexplained(page: str, fmt: str | None) -> list[str]:
    ok = allowed(fmt)
    return sorted({n for n in NUMBER.findall(main_text(page)) if n not in ok})


def test_every_figure_on_a_compat_page_is_in_a_result_file_or_is_a_count_of_them(
    site: Path,
) -> None:
    pages = ["compat", *[f"compat/{fmt}" for fmt in FORMATS]]
    assert len(pages) == 13
    for key in pages:
        fmt = None if key == "compat" else key.split("/", 1)[1]
        assert unexplained(text(site, key), fmt) == [], key


def test_the_figure_check_fires_on_a_number_the_results_do_not_hold(site: Path) -> None:
    """Negative control, and the empty-set control: the pages hold many figures, and one that no
    result file holds is reported."""
    page = text(site, "compat/zip")
    assert len(NUMBER.findall(main_text(page))) > 20
    tampered = page.replace("<main", "<main data-x", 1).replace(
        "</main>", "<p>9876 cells</p></main>", 1
    )
    assert unexplained(tampered, "zip") == ["9876"]


def test_each_page_has_its_own_title_description_and_twin(site: Path) -> None:
    for key in ["compat", *[f"compat/{fmt}" for fmt in FORMATS]]:
        html = text(site, key)
        title = re.search(r"<title>(.*?)</title>", html).group(1)  # type: ignore[union-attr]
        description = re.search(r'name="description" content="(.*?)"', html).group(1)  # type: ignore[union-attr]
        assert len(title) <= build.TITLE_LIMIT, (key, title)
        assert build.DESCRIPTION_FLOOR <= len(description) <= build.DESCRIPTION_LIMIT, key
        twin = (site / routes.disk_path(routes.twin_key(key))).read_text(encoding="utf-8")
        assert twin.startswith("# How standard libraries read"), key
        assert f"<{config.BASE_URL}{key}>" in twin


def test_outcomes_are_words_in_the_page_and_no_colour_carries_them(site: Path) -> None:
    html = text(site, "compat/wav")
    assert "style=" not in html and "color" not in html.lower().replace("colorspace", "")
    body = main_text(html)
    assert "refuses with" in body and "unknown format" in body, "the error is as raised"
    assert "no-reader" in body, "Go has no wav reader, and the page says so"
    assert "3.11 to 3.11" not in body, "a single version is not shown as a range"


def test_a_page_names_the_ranges_where_versions_disagree(site: Path) -> None:
    body = main_text(text(site, "compat/wav"))
    assert re.search(r"3\.\d+ to 3\.\d+ ", body) or re.search(r"\b3\.1\d\b", body)
    results = json.loads((RESULTS / "wav.json").read_text(encoding="utf-8"))
    per = next(
        row["cells"]["python/wave"]
        for row in results["files"]
        if row["path"] == "wav/sine-440hz-3s-48k-24bit-stereo.wav"
    )
    assert len({json.dumps(c, sort_keys=True) for c in per.values()}) > 1, "control: they disagree"


def test_groups_are_consecutive_runs_of_one_behaviour() -> None:
    cell_a, cell_b = {"outcome": "refuses", "error": "x"}, {"outcome": "reads", "props": {}}
    per = {"python-3.11": cell_a, "python-3.12": cell_a, "python-3.13": cell_b}
    made = compat.groups(per, ["python-3.11", "python-3.12", "python-3.13"])
    assert [(g["label"], g["cell"]["outcome"]) for g in made] == [
        ("3.11 to 3.12", "refuses"),
        ("3.13", "reads"),
    ]
    interleaved = {"python-3.11": cell_a, "python-3.12": cell_b, "python-3.13": cell_a}
    assert len(compat.groups(interleaved, list(interleaved))) == 3


def test_an_edge_file_that_is_meant_to_fail_says_so_in_the_words_of_its_outcome(site: Path) -> None:
    body = main_text(text(site, "compat/zip"))
    assert "this file is meant to be refused" in body
    assert compat.edge_note({"edge_outcome": "must-fail"}, "refuses") == "expected"
    assert "notable" in compat.edge_note({"edge_outcome": "must-fail"}, "reads")
    assert compat.edge_note({"edge_outcome": "varies"}, "reads") == ""


def test_compat_is_reserved_and_a_missing_results_directory_stops_the_build(tmp_path: Path) -> None:
    assert "compat" in build.RESERVED
    with pytest.raises(compat.CompatError, match="compat/results"):
        compat.load(tmp_path)


def test_the_format_pages_link_their_compat_page_and_only_those(site: Path) -> None:
    assert 'href="/compat/zip"' in text(site, "zip")
    assert 'href="/compat/pdf"' not in text(site, "pdf"), "control: pdf is not in scope"
    twin = (site / routes.disk_path(routes.twin_key("zip"))).read_text(encoding="utf-8")
    assert f"<{config.BASE_URL}compat/zip>" in twin


def test_llms_txt_has_one_line_for_the_scoreboard_and_the_sitemap_lists_every_page(
    site: Path,
) -> None:
    llms = text(site, "llms.txt")
    assert len([ln for ln in llms.splitlines() if f"{config.BASE_URL}compat" in ln]) == 1
    sitemap = text(site, "sitemap.xml")
    for key in ["compat", *[f"compat/{fmt}" for fmt in FORMATS]]:
        assert f"<loc>{config.BASE_URL}{key}</loc>" in sitemap, key


def test_the_status_page_names_the_agent_the_compat_run_sends(site: Path) -> None:
    assert config.COMPAT_USER_AGENT in text(site, "status")
