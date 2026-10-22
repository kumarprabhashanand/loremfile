"""Catalogue 1.11.0: VP9 and Opus in general Matroska, the one 1.10.0 file that drifts.

It shipped alone (docs/11 §7.9b) because libvpx and libopus choose SIMD kernels from the
CPU, so CI's bytes are the published ones. What sets it apart on its page is the codecs;
what sets it apart from `webm/720p-5s-vp9.webm` is the container, read from the EBML header.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from loremfile.build import load_generators
from loremfile.catalog import Catalog
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import load, validate

PATH = "mkv/vp9-opus-720p-5s.mkv"
CATALOG = Catalog.load()
load_generators()
load()


def build(path: str, directory: Path, **overrides: object) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    entry = CATALOG.by_path[path]
    context = GeneratorContext(path=path, workdir=directory)
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **(entry.params | overrides))
    return out if isinstance(out, bytes) else out.read_bytes()


def doctype(data: bytes) -> bytes:
    """The EBML DocType string (element 0x4282) from the header at the file's start."""
    at = data.index(b"\x42\x82", 0, 64)
    size = data[at + 2] & 0x7F  # a one-byte EBML size: 0x80 | length
    return data[at + 3 : at + 3 + size]


def test_it_is_marked_expected_drift_and_served_as_matroska() -> None:
    entry = CATALOG.by_path[PATH]
    assert entry.expected_drift and "SIMD" in entry.expected_drift
    assert entry.params["container"] == "matroska"
    assert CATALOG.mime_for(entry) == "video/x-matroska"


@pytest.mark.container
def test_it_validates_reproduces_here_and_an_h264_mkv_is_refused(tmp_path):
    data = build(PATH, tmp_path / "a")
    entry = CATALOG.by_path[PATH]
    assert validate(data, entry, CATALOG.mime_for(entry)).ok
    assert data == build(PATH, tmp_path / "b"), "reproducible on one machine; CI's bytes ship"
    h264 = build("mkv/720p-5s.mkv", tmp_path / "h264")
    assert not validate(h264, entry, CATALOG.mime_for(entry)).ok


@pytest.mark.container
def test_the_container_is_matroska_where_the_webm_file_says_webm(tmp_path):
    assert doctype(build(PATH, tmp_path / "mkv")) == b"matroska"
    assert doctype(build(PATH, tmp_path / "webm", container="webm")) == b"webm", "control"
