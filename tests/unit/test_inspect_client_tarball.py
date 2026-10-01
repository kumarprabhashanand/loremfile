"""The check that stands between the npm tarball and the registry (tools/inspect_client_tarball.py).

Every assertion is driven against a tarball built for the purpose, including the ones that
must fail — npm does not allow publishing a version twice, so this guard gets exactly one
chance per release and cannot be one nobody has watched fire.
"""

from __future__ import annotations

import importlib.util
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "inspect_tarball", ROOT / "tools" / "inspect_client_tarball.py"
)
assert _spec and _spec.loader
inspect_tarball = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inspect_tarball)

MANIFEST: dict[str, Any] = {
    "name": "loremfile",
    "version": "0.1.0",
    "type": "module",
    "bin": {"loremfile": "bin/loremfile.js"},
    "engines": {"node": ">=20"},
}
CLEAN = {
    "package/README.md": "# loremfile",
    "package/bin/loremfile.js": "#!/usr/bin/env node\n",
    "package/src/api.js": "",
    "package/src/cli.js": "",
}


def build(
    tmp_path: Path,
    members: dict[str, str],
    *,
    manifest: dict[str, Any] | None = None,
    links: tuple[str, ...] = (),
) -> Path:
    tarball = tmp_path / "loremfile-0.1.0.tgz"
    with tarfile.open(tarball, "w:gz") as archive:
        files = {**members, "package/package.json": json.dumps(manifest or MANIFEST)}
        for name, body in files.items():
            data = body.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        for name in links:
            link = tarfile.TarInfo(name)
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            archive.addfile(link)
    return tarball


def test_a_clean_tarball_passes(tmp_path: Path) -> None:
    """The control: the refusals below are about their subject, not a check that refuses
    every tarball it is shown."""
    assert inspect_tarball.problems(build(tmp_path, CLEAN), expected_version="0.1.0") == []


def test_the_real_tarball_passes_if_one_has_been_packed() -> None:
    """Against the artifact `npm pack` actually produces, when it is there."""
    packed = sorted((ROOT / "client-js").glob("loremfile-*.tgz"))
    if not packed:
        pytest.skip("no tarball packed here; the publishing workflow packs one first")
    assert inspect_tarball.problems(packed[-1], expected_version=None) == []


def test_a_file_from_outside_the_client_is_refused(tmp_path: Path) -> None:
    tarball = build(tmp_path, {**CLEAN, "package/test/commands.test.js": ""})
    [problem] = inspect_tarball.problems(tarball, expected_version=None)
    assert "package/test/commands.test.js" in problem


def test_an_entry_outside_the_package_directory_is_refused(tmp_path: Path) -> None:
    tarball = build(tmp_path, {**CLEAN, "../outside.js": ""})
    problems = inspect_tarball.problems(tarball, expected_version=None)
    assert any("../outside.js" in problem for problem in problems), problems


def test_a_link_is_refused(tmp_path: Path) -> None:
    tarball = build(tmp_path, CLEAN, links=("package/src/link.js",))
    [problem] = inspect_tarball.problems(tarball, expected_version=None)
    assert "package/src/link.js is not a plain file" in problem


@pytest.mark.parametrize("part", ["infra", "generators", "validators", "site", "upload", "release"])
def test_each_piece_of_repository_tooling_is_refused_by_name(tmp_path: Path, part: str) -> None:
    """Named one at a time: a list that lost an entry would still pass a test that only
    checked the list was non-empty."""
    tarball = build(tmp_path, {**CLEAN, f"package/src/{part}/helper.js": ""})
    problems = inspect_tarball.problems(tarball, expected_version=None)
    assert any(f"{part} tooling" in problem for problem in problems), problems


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dependencies", {"left-pad": "1.3.0"}),
        ("optionalDependencies", {"left-pad": "1.3.0"}),
        ("peerDependencies", {"left-pad": "1.3.0"}),
        ("bundleDependencies", ["left-pad"]),
        ("bundledDependencies", ["left-pad"]),
        ("scripts", {"postinstall": "node -e 1"}),
        ("gypfile", True),
    ],
)
def test_anything_that_would_install_or_run_more_is_refused(
    tmp_path: Path, field: str, value: object
) -> None:
    tarball = build(tmp_path, CLEAN, manifest={**MANIFEST, field: value})
    [problem] = inspect_tarball.problems(tarball, expected_version=None)
    assert f"declares {field}" in problem


def test_another_package_name_is_refused(tmp_path: Path) -> None:
    tarball = build(tmp_path, CLEAN, manifest={**MANIFEST, "name": "lorem-file"})
    [problem] = inspect_tarball.problems(tarball, expected_version=None)
    assert "'lorem-file'" in problem


def test_a_version_that_is_not_the_tags_is_refused(tmp_path: Path) -> None:
    tarball = build(tmp_path, CLEAN, manifest={**MANIFEST, "version": "0.2.0"})
    [problem] = inspect_tarball.problems(tarball, expected_version="0.1.0")
    assert "'0.2.0'" in problem and "'0.1.0'" in problem


def test_a_tarball_without_its_package_json_is_refused(tmp_path: Path) -> None:
    tarball = tmp_path / "loremfile-0.1.0.tgz"
    with tarfile.open(tarball, "w:gz") as archive:
        info = tarfile.TarInfo("package/src/api.js")
        archive.addfile(info, io.BytesIO(b""))
    problems = inspect_tarball.problems(tarball, expected_version=None)
    assert any("no package/package.json" in problem for problem in problems), problems


def test_an_empty_tarball_is_refused(tmp_path: Path) -> None:
    """An empty tarball satisfies "every entry belongs to the client" vacuously."""
    tarball = tmp_path / "loremfile-0.1.0.tgz"
    with tarfile.open(tarball, "w:gz"):
        pass
    [problem] = inspect_tarball.problems(tarball, expected_version=None)
    assert "holds nothing" in problem


def test_the_exit_code_is_what_a_workflow_reads(tmp_path: Path) -> None:
    clean = build(tmp_path, CLEAN)
    assert inspect_tarball.main(["prog", str(clean), "0.1.0"]) == 0
    assert inspect_tarball.main(["prog", str(clean), "9.9.9"]) == 1
    assert inspect_tarball.main(["prog"]) == 2
