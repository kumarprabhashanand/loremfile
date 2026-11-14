"""/compat: the scoreboard's pages, built only from `compat/results/` (docs/07 §8).

Every sentence about a library here is generated from a result file, never written by hand. The
build stays offline: nothing is fetched, and a results directory that is missing or does not
hold together stops it. This module holds no page machinery (that is `build.py`); it turns the
results into the figures, the sentences and the Markdown the pages show.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from loremfile import config

#: The words a cell can carry, and what each means (compat/README.md). Definitions of the
#: vocabulary, not claims about any library.
OUTCOME_DEFINITIONS: dict[str, str] = {
    "reads": "No error, and every property the reader reported equals the manifest's.",
    "differs": "No error, and at least one reported property does not equal the manifest's.",
    "refuses": "The reader raised or returned an error.",
    "crashes": "The process died, printed no result, or passed its time limit.",
    "no-reader": "The runtime's standard library has no reader for this format.",
    "not-run": "The runtime, adapter or fetch could not be set up. Never counted.",
}
TALLIED = ("reads", "differs", "refuses", "crashes")
EDGE_NOTE = {
    "must-fail": "this file is meant to be refused",
    "may-recover": "a reader may refuse it or recover what it can",
    "varies": "readers differ, and none is wrong",
}
ADAPTER_LINK = f"{config.SOURCE_URL}/blob/main/compat/"


class CompatError(Exception):
    """The results do not hold together; the build stops rather than publish them."""


@dataclass(frozen=True)
class Results:
    run: dict[str, Any]
    formats: dict[str, dict[str, Any]]
    config: dict[str, Any]
    runtimes: list[dict[str, Any]]


def scope_formats(root: Path) -> frozenset[str]:
    """The formats with a compat page, from readers.yaml alone (no results needed)."""
    readers = yaml.safe_load((root / "compat" / "readers.yaml").read_text(encoding="utf-8"))
    return frozenset(readers["scope"]["formats"])


def load(root: Path) -> Results:
    directory = root / "compat" / "results"
    try:
        run = json.loads((directory / "_run.json").read_text(encoding="utf-8"))
        readers = yaml.safe_load((root / "compat" / "readers.yaml").read_text(encoding="utf-8"))
        runtimes = yaml.safe_load((root / "compat" / "runtimes.yaml").read_text(encoding="utf-8"))
        formats = {
            fmt: json.loads((directory / f"{fmt}.json").read_text(encoding="utf-8"))
            for fmt in readers["scope"]["formats"]
        }
    except (OSError, ValueError, KeyError) as error:
        raise CompatError(
            f"compat/results: {error}; run compat.yml and commit its results"
        ) from error
    return Results(run, formats, readers, runtimes["runtimes"])


def version_label(versions: list[str]) -> str:
    """`3.11`, `3.11 to 3.13`, from `python-3.11` .. `python-3.13`, in the order given."""
    names = [v.split("-", 1)[1] for v in versions]
    return names[0] if len(names) == 1 else f"{names[0]} to {names[-1]}"


def groups(per: dict[str, dict[str, Any]], order: list[str]) -> list[dict[str, Any]]:
    """Consecutive runtime versions that did the same thing, as one group each.

    `per` is {runtime-version: cell}; `order` the runtime's versions ascending. A group is
    {"versions": [...], "label": "3.11 to 3.12", "cell": {...}}.
    """
    found: list[dict[str, Any]] = []
    for version in order:
        cell = per.get(version)
        if cell is None:
            continue
        if found and found[-1]["cell"] == cell:
            found[-1]["versions"].append(version)
        else:
            found.append({"versions": [version], "cell": cell})
    for group in found:
        group["label"] = version_label(group["versions"])
    return found


def show(value: Any) -> str:  # noqa: ANN401 - any JSON value a reader reported
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(show(v) for v in value) + "]"
    return str(value)


def props_text(values: dict[str, Any]) -> str:
    return ", ".join(f"{name} {show(value)}" for name, value in sorted(values.items()))


def difference_text(name: str, found: dict[str, Any], expect: dict[str, Any], fmt: str) -> str:
    reported, expected = show(found["reported"]), show(found["expected"])
    if fmt == "csv" and name == "rows" and expect.get("has_header"):
        return (
            f"reports {name} {reported} where the file holds {expected} records: "
            f"{show(expect['rows'])} data rows and a header"
        )
    return f"reports {name} {reported} where the manifest has {expected}"


def cell_text(cell: dict[str, Any], row: dict[str, Any], fmt: str) -> str:
    """What a cell did, in the words of its result: the error as raised, the values as reported."""
    outcome = cell["outcome"]
    if outcome == "reads":
        shown = props_text(cell["props"])
        return f"reports {shown}" if shown else "reports nothing to compare"
    if outcome == "differs":
        return "; ".join(
            difference_text(name, found, row["expect"], fmt)
            for name, found in sorted(cell["differs"].items())
        )
    if outcome == "refuses":
        kind = f"{cell['error_type']}: " if cell.get("error_type") else ""
        return f"with {kind}{cell['error']}"
    return f"({cell['detail']})" if cell.get("detail") else ""


def edge_note(row: dict[str, Any], outcome: str) -> str:
    """For an `edge/` file: what its own `outcome` says about this cell, in its words."""
    expected = row.get("edge_outcome")
    if expected == "must-fail":
        return "expected" if outcome == "refuses" else "notable: this file is meant to be refused"
    return ""


def runtime_order(results: Results, runtime: str) -> list[str]:
    for entry in results.runtimes:
        if entry["id"] == runtime:
            return [f"{runtime}-{v}" for v in sorted(entry["versions"], key=_version_key)]
    raise CompatError(f"unknown runtime {runtime!r}")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def tally(results: Results, fmt: str) -> dict[str, int]:
    """Cells of the format's ordinary files by outcome, every runtime version counted."""
    counts = dict.fromkeys(TALLIED, 0)
    for row in results.formats[fmt]["files"]:
        if row["kind"] != "ordinary":
            continue
        for per in row["cells"].values():
            for cell in per.values():
                if cell["outcome"] in counts:
                    counts[cell["outcome"]] += 1
    return counts


def unread_notes(results: Results, fmt: str) -> list[str]:
    """For an `edge/` file labelled `varies` that no reader read: one line saying so.

    The label describes what the format allows, not what readers did, so it is never changed
    to fit; a page that shows every reader refusing it says that in a sentence instead.
    """
    document = results.formats[fmt]
    notes = []
    for row in document["files"]:
        if row["kind"] != "edge" or row["edge_outcome"] != "varies":
            continue
        outcomes = [cell["outcome"] for per in row["cells"].values() for cell in per.values()]
        if outcomes and not {"reads", "differs"} & set(outcomes) and "refuses" in outcomes:
            readers = len(row["cells"])
            runtimes = len({reader.split("/", 1)[0] for reader in row["cells"]})
            notes.append(
                f"None of the {readers} readers, in {counted(runtimes, 'runtime')}, read "
                f"{row['path']}. Its outcome, varies, is what the format allows, not what these "
                "readers did."
            )
    return notes


def runtime_name(results: Results, runtime: str) -> str:
    return str(next(r["name"] for r in results.runtimes if r["id"] == runtime))


def counted(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


DESCRIPTION_BAND = (120, 155)


def banded(text: str, where: str) -> str:
    low, high = DESCRIPTION_BAND
    if not low <= len(text) <= high:
        raise CompatError(f"{where}: the description is {len(text)} characters, not {low}-{high}")
    return text


def format_figures(results: Results, fmt: str) -> dict[str, int]:
    document = results.formats[fmt]
    versions = sum(1 for r in document["readers"] for _ in runtime_order(results, r["runtime"]))
    return {
        "files": len(document["files"]),
        "readers": len(document["readers"]),
        "versions": len(
            {v for r in document["readers"] for v in runtime_order(results, r["runtime"])}
        ),
        "cells": versions,
    }


def format_description(results: Results, fmt: str, label: str) -> str:
    n = format_figures(results, fmt)
    return banded(
        f"{counted(n['files'], label + ' file')} from loremfile.dev, given to "
        f"{counted(n['readers'], 'standard-library reader')} in "
        f"{counted(n['versions'], 'runtime version')}: "
        "which read them, which refuse, which differ.",
        f"compat/{fmt}",
    )


def format_summary(results: Results, fmt: str, label: str) -> str:
    n = format_figures(results, fmt)
    found = tally(results, fmt)
    cells = ", ".join(f"{name} {found[name]}" for name in TALLIED)
    return (
        f"{counted(n['files'], label + ' file')} given to {counted(n['readers'], 'reader')} in "
        f"{counted(n['versions'], 'runtime version')}. Cells of the ordinary files: {cells}."
    )


def index_description(results: Results) -> str:
    names = [r["name"] for r in results.runtimes]
    runtimes = " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)
    return banded(
        f"How the standard libraries of {runtimes} read our sample files: who opens them, who "
        "refuses, who disagrees with the manifest.",
        "compat",
    )


def adapter_url(results: Results, runtime: str) -> str:
    entry = next(r for r in results.runtimes if r["id"] == runtime)
    return f"{ADAPTER_LINK}{entry['adapter']}"


def method_sentences(results: Results) -> list[str]:
    scope = results.config["scope"]
    return [
        "Each file is fetched once from this site and checked against the hash in manifest.json "
        "before any reader sees it.",
        "Each reader is one module in one runtime, given each file by an adapter that reads all "
        "of it with the module's default settings, and reports only what the module gives "
        "natively.",
        f"Every reader and file is one process with a limit of {scope['timeout_seconds']} seconds, "
        "run in every supported version of the runtime.",
        "What a reader reports is compared with the manifest's measured properties for that file; "
        "the exceptions to that are named below.",
        f"Files over {scope['max_bytes'] // 1_000_000} MB are skipped and listed, and a reader "
        "whose two controls do not hold is shown as not-run.",
    ]


def run_rows(results: Results) -> list[dict[str, str]]:
    rows = []
    for key, info in results.run["runtimes"].items():
        runtime, version = key.split("-", 1)
        name = next(r["name"] for r in results.runtimes if r["id"] == runtime)
        rows.append(
            {
                "name": f"{name} {version}",
                "resolved": info.get("resolved") or "not-run",
                "detail": info.get("not_run") or "",
            }
        )
    return rows


def format_context(results: Results, fmt: str, size: Callable[[int], str]) -> dict[str, Any]:
    """Everything a /compat/{format} page shows, as plain data."""
    document = results.formats[fmt]
    readers = document["readers"]
    columns = [
        {
            "id": r["id"],
            "module": r["module"],
            "runtime": r["runtime"],
            "runtime_name": runtime_name(results, r["runtime"]),
            "docs": r["docs"],
            "adapter": adapter_url(results, r["runtime"]),
        }
        for r in readers
    ]
    order = {r["id"]: runtime_order(results, r["runtime"]) for r in readers}
    rows = []
    for row in document["files"]:
        cells: list[dict[str, Any]] = []
        for column in columns:
            if column["id"] not in row["cells"]:
                # Not handed this file (`when` in readers.yaml); where the runtime has no reader
                # for the file at all, that is the cell's outcome.
                missing = column["runtime"] in row.get("no_reader", [])
                cells.append({"state": "no-reader" if missing else "not-given", "groups": []})
                continue
            made = groups(row["cells"][column["id"]], order[column["id"]])
            cells.append(
                {
                    "state": "run",
                    "groups": [
                        {
                            "label": group["label"] if len(made) > 1 else "",
                            "outcome": group["cell"]["outcome"],
                            "text": cell_text(group["cell"], row, fmt),
                            "note": edge_note(row, group["cell"]["outcome"]),
                        }
                        for group in made
                    ],
                }
            )
        rows.append(
            {
                "path": row["path"],
                "name": row["path"].split("/", 1)[1],
                "url": row["url"],
                "size": size(row["bytes"]),
                "kind": row["kind"],
                "role": row["role"],
                "edge": EDGE_NOTE.get(row["edge_outcome"] or "", ""),
                "edge_outcome": row["edge_outcome"],
                "expect": props_text({k: v for k, v in row["expect"].items() if k != "has_header"}),
                "cells": cells,
            }
        )
    return {
        "format": fmt,
        "columns": columns,
        "no_reader": [
            {
                "runtime": runtime,
                "name": runtime_name(results, runtime),
                "reason": results.config["no_reader"][runtime][fmt],
            }
            for runtime in document["no_reader"]
        ],
        "notes": unread_notes(results, fmt),
        "routing": [r for r in results.config["scope"].get("routing", []) if r["format"] == fmt],
        "rows": rows,
        "skipped": [{**s, "size": size(s["bytes"])} for s in document["skipped"]],
        "tally": tally(results, fmt),
        "result_url": f"{ADAPTER_LINK}results/{fmt}.json",
    }


def index_context(results: Results) -> dict[str, Any]:
    by_format = []
    for fmt in results.config["scope"]["formats"]:
        document = results.formats[fmt]
        by_format.append(
            {
                "format": fmt,
                "readers": document["readers"],
                "no_reader": [runtime_name(results, rt) for rt in document["no_reader"]],
                "files": len(document["files"]),
                "tally": tally(results, fmt),
                "result_url": f"{ADAPTER_LINK}results/{fmt}.json",
            }
        )
    return {
        "outcomes": list(OUTCOME_DEFINITIONS.items()),
        "method": method_sentences(results),
        "exceptions": results.config["scope"]["exceptions"],
        "date": results.run["date"],
        "catalog_version": results.run["catalog_version"],
        "runs": run_rows(results),
        "sources": [
            {
                "name": r["name"],
                "source": r["source"],
                "supported": r["supported"],
                "checked": r["checked"],
            }
            for r in results.runtimes
        ],
        "by_format": by_format,
        "run_url": f"{ADAPTER_LINK}results/_run.json",
    }


def cell_markdown(group: dict[str, Any]) -> str:
    when = f"{group['label']}: " if group["label"] else ""
    text = f" {group['text']}" if group["text"] else ""
    note = f" ({group['note']})" if group["note"] else ""
    return f"{when}**{group['outcome']}**{text}{note}".replace("|", "\\|")


def format_twin(page_context: dict[str, Any]) -> str:
    """The format page as Markdown: one table, a row per file and a column per reader."""
    columns = page_context["columns"]
    head = [
        "File",
        "Manifest says",
        *[c["id"] for c in columns],
        *[f"{r['name']} (no reader)" for r in page_context["no_reader"]],
    ]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for row in page_context["rows"]:
        link = f"[`{row['path']}`]({config.BASE_URL}{row['path']}) ({row['size']})"
        cells = [
            "<br>".join(cell_markdown(g) for g in cell["groups"])
            if cell["state"] == "run"
            else ("**no-reader**" if cell["state"] == "no-reader" else "not given this file")
            for cell in row["cells"]
        ]
        cells += ["**no-reader**"] * len(page_context["no_reader"])
        lines.append("| " + " | ".join([link, row["expect"] or "nothing compared", *cells]) + " |")
    out = ["\n".join(lines)]
    if page_context["skipped"]:
        out.append(
            "Skipped, over the size limit: "
            + ", ".join(f"`{s['path']}` ({s['size']})" for s in page_context["skipped"])
            + "."
        )
    out.extend(f"{r['text']}" for r in page_context["routing"])
    out.extend(
        f"{r['name']} has no reader for these files. {r['reason']}"
        for r in page_context["no_reader"]
    )
    out.extend(page_context["notes"])
    out.append(f"The results as JSON: <{page_context['result_url']}>.")
    return "\n\n".join(out)


def index_twin(context: dict[str, Any]) -> str:
    run = f"Run on {context['date']} against catalogue {context['catalog_version']}."
    runs = "\n".join(
        f"- {r['name']}: {r['resolved']}" + (f" ({r['detail']})" if r["detail"] else "")
        for r in context["runs"]
    )
    head = "| Format | Readers | No reader in | Files | " + " | ".join(TALLIED) + " |"
    rows = [
        f"| [{row['format']}]({config.BASE_URL}compat/{row['format']}) | "
        + ", ".join(r["id"] for r in row["readers"])
        + f" | {', '.join(row['no_reader']) or '-'} | {row['files']} | "
        + " | ".join(str(row["tally"][k]) for k in TALLIED)
        + " |"
        for row in context["by_format"]
    ]
    outcomes = "\n".join(f"- **{name}**: {text}" for name, text in context["outcomes"])
    sources = "\n".join(
        f"- {s['name']}: {s['source']} ({s['supported']}; read {s['checked']})"
        for s in context["sources"]
    )
    return "\n\n".join(
        [
            f"## Outcomes\n\n{outcomes}",
            "## Method\n\n" + " ".join(context["method"]),
            "## Named exceptions\n\n"
            + "\n".join(
                f"- **{e['name']}** ({', '.join(e['applies'])}): {e['text']}"
                for e in context["exceptions"]
            ),
            f"## This run\n\n{run}\n\n{runs}\n\n{sources}",
            "## Readers by format\n\n"
            + "\n".join([head, "|" + "---|" * (4 + len(TALLIED)), *rows]),
        ]
    )
