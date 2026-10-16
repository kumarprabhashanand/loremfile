"""`tone_hz` and `chain_tone_hz` as the media validator publishes them (catalogue 1.9.1).

util/tone.py is tested on synthetic samples in test_tone.py; these run the whole path on
real fixtures built by their generators: ffmpeg decodes, Goertzel measures, the validator
publishes. Each case is one a reader could get wrong: a silent file, two channels with two
tones, and a chained file whose second chain a one-window decode would never reach.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from loremfile.build import load_generators
from loremfile.catalog import Catalog
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import load, validate

CATALOG = Catalog.load()
load_generators()
load()


def props_of(path: str, directory: Path) -> dict:
    entry = CATALOG.by_path[path]
    context = GeneratorContext(path=path, workdir=directory)
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **entry.params)
    data = out if isinstance(out, bytes) else out.read_bytes()
    report = validate(data, entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures
    return report.props


@pytest.mark.container
def test_a_silent_file_publishes_no_tone(tmp_path: Path) -> None:
    assert "tone_hz" not in props_of("mp3/silence-5s.mp3", tmp_path)


@pytest.mark.container
def test_each_channel_gets_its_own_tone(tmp_path: Path) -> None:
    assert props_of("mp3/stereo-lr-5s.mp3", tmp_path)["tone_hz"] == [440.0, 880.0]


@pytest.mark.container
def test_a_chained_file_records_each_chains_tone(tmp_path: Path) -> None:
    props = props_of("ogg/chained-2-streams-10s.ogg", tmp_path)
    assert props["tone_hz"] == [440.0, 440.0], "a decode reads the first chain alone"
    assert props["chain_tone_hz"] == [[440.0, 440.0], [880.0, 880.0]]


@pytest.mark.container
def test_a_single_chain_file_has_no_chain_tones(tmp_path: Path) -> None:
    props = props_of("ogg/vorbis-mono-22k-10s.ogg", tmp_path)
    assert props["tone_hz"] == [440.0]
    assert "chain_tone_hz" not in props
