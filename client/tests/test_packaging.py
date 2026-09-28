"""The wheel carries the client and nothing else (the CLI spec's packaging split).

Read off the built artifact, not the source tree: the point is what a user installs. CI
builds the wheel into `dist/` before running these, and the absence of one fails rather
than skips — a packaging guard that quietly does not run is the packaging guard that lets
the deploy tooling out.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1]
#: Nothing whose path contains these may ever be in the wheel. Named, not counted.
NEVER = ("infra", "generators", "validators", "site", "upload", "release", "catalog", "manifest")


def wheel() -> Path:
    built = sorted((CLIENT / "dist").glob("*.whl"))
    assert built, f"no wheel in {CLIENT / 'dist'}; build it first: python -m build --wheel"
    return built[-1]


def members() -> list[str]:
    with zipfile.ZipFile(wheel()) as archive:
        return archive.namelist()


def test_every_module_in_the_wheel_is_the_client() -> None:
    modules = [name for name in members() if name.endswith(".py")]
    assert modules, "empty-set control: the wheel was read and holds modules"
    assert all(name.startswith("loremfile_client/") for name in modules), modules


def test_the_wheel_carries_no_repository_tooling() -> None:
    for name in members():
        lowered = name.lower()
        assert not any(f"/{part}" in lowered or lowered.startswith(part) for part in NEVER), name


def test_the_console_script_is_the_client_entry_point() -> None:
    with zipfile.ZipFile(wheel()) as archive:
        entry_points = next(n for n in archive.namelist() if n.endswith("entry_points.txt"))
        text = archive.read(entry_points).decode()
    assert "loremfile = loremfile_client.cli:main" in text


def test_the_wheel_declares_no_dependencies() -> None:
    with zipfile.ZipFile(wheel()) as archive:
        metadata = next(n for n in archive.namelist() if n.endswith("METADATA"))
        text = archive.read(metadata).decode()
    assert "Requires-Dist:" not in text, "the client must install nothing else"
    assert "Requires-Python: >=3.11" in text
