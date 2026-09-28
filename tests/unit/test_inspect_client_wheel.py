"""The check that stands between a wheel and PyPI (tools/inspect_client_wheel.py).

Every assertion is driven against a wheel built for the purpose, including the ones that
must fail — PyPI does not allow replacing a version, so this guard gets exactly one
chance per release and cannot be one nobody has watched fire.
"""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "inspect_wheel", ROOT / "tools" / "inspect_client_wheel.py"
)
assert _spec and _spec.loader
inspect_wheel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inspect_wheel)

METADATA = "Metadata-Version: 2.4\nName: loremfile\nVersion: 0.1.0\n"


def build(tmp_path: Path, members: dict[str, str], *, version: str = "0.1.0") -> Path:
    wheel = tmp_path / "loremfile-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
        archive.writestr("loremfile-0.1.0.dist-info/METADATA", METADATA.replace("0.1.0", version))
    return wheel


CLEAN = {
    "loremfile_client/__init__.py": "__version__ = '0.1.0'",
    "loremfile_client/api.py": "",
    "loremfile_client/cli.py": "",
}


def test_a_clean_wheel_passes(tmp_path: Path) -> None:
    """The control: the refusals below are about their subject, not a check that refuses
    every wheel it is shown."""
    assert inspect_wheel.problems(build(tmp_path, CLEAN), expected_version="0.1.0") == []


def test_the_real_wheel_passes_if_one_has_been_built() -> None:
    """Against the artifact this repository actually produces, when it is there."""
    built = sorted((ROOT / "client" / "dist").glob("*.whl"))
    if not built:
        pytest.skip("no client wheel built here; CI builds one before it inspects")
    assert inspect_wheel.problems(built[-1], expected_version=None) == []


def test_a_module_from_outside_the_package_is_refused(tmp_path: Path) -> None:
    wheel = build(tmp_path, {**CLEAN, "loremfile/cli.py": "# the repository's own CLI"})
    [problem] = inspect_wheel.problems(wheel, expected_version=None)
    assert "loremfile/cli.py" in problem


@pytest.mark.parametrize("part", ["infra", "generators", "validators", "site", "upload", "release"])
def test_each_piece_of_repository_tooling_is_refused_by_name(tmp_path: Path, part: str) -> None:
    """Named one at a time: a list that lost an entry would still pass a test that only
    checked the list was non-empty."""
    wheel = build(tmp_path, {**CLEAN, f"loremfile_client/{part}/helper.py": ""})
    problems = inspect_wheel.problems(wheel, expected_version=None)
    assert any(part in problem for problem in problems), problems


def test_a_version_that_is_not_the_tags_is_refused(tmp_path: Path) -> None:
    [problem] = inspect_wheel.problems(
        build(tmp_path, CLEAN, version="0.2.0"), expected_version="0.1.0"
    )
    assert "'0.2.0'" in problem and "'0.1.0'" in problem


def test_a_wheel_with_no_modules_is_refused(tmp_path: Path) -> None:
    """An empty wheel satisfies "every module belongs to the package" vacuously."""
    [problem] = inspect_wheel.problems(build(tmp_path, {}), expected_version=None)
    assert "no Python modules" in problem


def test_the_exit_code_is_what_a_workflow_reads(tmp_path: Path) -> None:
    clean = build(tmp_path, CLEAN)
    assert inspect_wheel.main(["prog", str(clean), "0.1.0"]) == 0
    assert inspect_wheel.main(["prog", str(clean), "9.9.9"]) == 1
    assert inspect_wheel.main(["prog"]) == 2
