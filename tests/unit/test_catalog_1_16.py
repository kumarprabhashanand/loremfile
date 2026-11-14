"""Catalogue 1.16.0: the eleven phase-1 audio rows that nothing had built, and the `ogv` and `ts`
aliases that ride with them.

Named from `catalog/_plan.yaml`, not by subtraction. The quick rows are built twice in fresh
directories and must match themselves; the 100 MB WAV is built once and held to its arithmetic
(CI's `manifest check` rebuilds it too). Every control builds the file without its one declared
difference and watches the validator refuse it for the property that difference carries.

The four new WAV rows get one more check than the others (owner, 2026-11-14): the standard
libraries' scoreboard (`compat/`, docs/07 §8) compares their `channels`, `sample_rate`, `bit_depth`
and `duration_ms` with five libraries, and a disagreement it publishes has to be the library's.
So the four props are read here from the file's own header by `struct`, with no ffprobe, and held
to the manifest; and what the readers are expected to say about the two rows where readers differ
is held to the bytes that explain it.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import pytest
import yaml

from loremfile.build import load_generators
from loremfile.catalog import Catalog
from loremfile.generators import media_audio
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util import tone
from loremfile.util.determinism import deterministic
from loremfile.util.ffmpeg import decode_pcm
from loremfile.validators import load, validate
from loremfile.validators.media import _wav_header

ROOT = Path(__file__).resolve().parents[2]
CATALOG = Catalog.load()
MANIFEST = {e["path"]: e for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
PLAN = yaml.safe_load((ROOT / "catalog" / "_plan.yaml").read_text(encoding="utf-8"))["rows"]
AUDIO_FORMATS = ("mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "aiff")
load_generators()
load()

MP3 = (
    "mp3/sweep-20-20khz-10s.mp3",
    "mp3/noise-white-5s.mp3",
    "mp3/128kbps-30s.mp3",
    "mp3/320kbps-30s.mp3",
    "mp3/vbr-v2-30s.mp3",
    "mp3/mono-22khz-64kbps-30s.mp3",
)
WAV = (
    "wav/sine-440hz-3s-8k-8bit-mono.wav",
    "wav/sine-440hz-3s-96k-32bit-float.wav",
    "wav/silence-5s.wav",
    "wav/100mb.wav",
)
FLAC = ("flac/24bit-96k-10s.flac",)
PATHS = MP3 + WAV + FLAC
QUICK = tuple(p for p in PATHS if p != "wav/100mb.wav")


def build(path: str, directory: Path, **overrides: Any) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    entry = CATALOG.by_path[path]
    context = GeneratorContext(path=path, workdir=directory)
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **(entry.params | overrides))
    return out if isinstance(out, bytes) else out.read_bytes()


def failures(path: str, data: bytes) -> list[str]:
    entry = CATALOG.by_path[path]
    return validate(data, entry, CATALOG.mime_for(entry)).failures


def props_of(path: str, data: bytes) -> dict[str, Any]:
    entry = CATALOG.by_path[path]
    report = validate(data, entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures
    return report.props


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("catalog-1-16")
    return {path: build(path, root / str(index)) for index, path in enumerate(QUICK)}


# --- the batch ------------------------------------------------------------------------------


def test_the_batch_is_the_audio_rows_of_the_plan_that_nothing_had_built() -> None:
    plan = [f"{r['format']}/{r['name']}" for r in PLAN if r["format"] in AUDIO_FORMATS]
    assert len(plan) == 27 and set(PATHS) <= set(plan)
    before = [p for p in plan if p not in PATHS]
    assert len(before) == 16 and all(p in MANIFEST for p in before)
    assert {p for p, e in MANIFEST.items() if e["added_in"] == "1.16.0"} == {
        *PATHS,
        "ogv/sample.ogv",
        "ts/sample.ts",
    }
    assert {fmt: sum(p.startswith(f"{fmt}/") for p in PATHS) for fmt in ("mp3", "wav", "flac")} == {
        "mp3": 6,
        "wav": 4,
        "flac": 1,
    }
    assert all(CATALOG.by_path[p].phase == 1 for p in PATHS)
    assert not [p for p in PATHS if CATALOG.by_path[p].expected_drift], "none drifts here"


@pytest.mark.container
@pytest.mark.parametrize("path", QUICK)
def test_each_quick_file_validates_and_reproduces_in_a_fresh_directory(path, built, tmp_path):
    assert failures(path, built[path]) == []
    assert built[path] == build(path, tmp_path)


# --- mp3 ------------------------------------------------------------------------------------


def first_frame(data: bytes) -> int:
    """Where the first MPEG audio frame starts: the first 11-bit sync word."""
    return next(i for i in range(len(data) - 1) if data[i] == 0xFF and data[i + 1] & 0xE0 == 0xE0)


@pytest.mark.container
def test_the_sweep_rises_from_the_bottom_of_the_range_toward_the_top(built, tmp_path) -> None:
    """A description says 20 to 20,000 hertz, linearly, so it is measured: the dominant
    frequency half a second, three and five seconds in is that line's value there. (Higher up
    the encoder's own lowpass takes the signal, which is what a bitrate row is for.)"""
    mp3 = tmp_path / "sweep.mp3"
    mp3.write_bytes(built["mp3/sweep-20-20khz-10s.mp3"])
    found = []
    for centre in (0.5, 3.0, 5.0):
        window = decode_pcm(mp3, channels=2, start=centre - 0.06, seconds=0.12, rate=24000)
        frequency, _purity = tone.dominant(list(window[0]), 24000)
        found.append(frequency)
        assert abs(frequency - (20 + 1998 * centre)) < 250, (centre, frequency)
    assert found == sorted(found), "it rises"


@pytest.mark.container
def test_neither_the_sweep_nor_the_noise_publishes_a_tone_and_a_sine_does(built, tmp_path) -> None:
    for path in ("mp3/sweep-20-20khz-10s.mp3", "mp3/noise-white-5s.mp3"):
        assert "tone_hz" not in props_of(path, built[path]), path
    sine = build("mp3/sweep-20-20khz-10s.mp3", tmp_path, source="sine")
    assert props_of("mp3/sweep-20-20khz-10s.mp3", sine)["tone_hz"] == [440.0, 440.0], "control"


@pytest.mark.container
def test_the_noise_is_seeded_and_a_different_seed_is_different_noise(built, tmp_path, monkeypatch):
    path = "mp3/noise-white-5s.mp3"
    assert media_audio.NOISE_SEED == 1 and media_audio.NOISE_AMPLITUDE == 0.5
    monkeypatch.setattr(media_audio, "NOISE_SEED", 2)
    assert build(path, tmp_path) != built[path], "control: the seed is what makes it this noise"


@pytest.mark.container
def test_a_bitrate_row_is_refused_at_any_other_rate(built, tmp_path) -> None:
    assert props_of("mp3/128kbps-30s.mp3", built["mp3/128kbps-30s.mp3"])["bitrate_kbps"] == 128.0
    assert props_of("mp3/320kbps-30s.mp3", built["mp3/320kbps-30s.mp3"])["bitrate_kbps"] == 320.0
    low = build("mp3/320kbps-30s.mp3", tmp_path, bitrate="128k")
    assert any("bitrate_kbps" in f for f in failures("mp3/320kbps-30s.mp3", low))


@pytest.mark.container
def test_128kbps_is_the_sweep_because_the_sine_at_that_rate_is_a_published_file(
    built, tmp_path
) -> None:
    """The description's claim: a thirty-second 440 Hz sine at 128 kbps is sine-440hz-30s.mp3
    byte for byte, so building it again would have published the same bytes under a new name."""
    sine = build("mp3/128kbps-30s.mp3", tmp_path, source="sine")
    assert hashlib.sha256(sine).hexdigest() == MANIFEST["mp3/sine-440hz-30s.mp3"]["sha256"]
    assert built["mp3/128kbps-30s.mp3"] != sine


@pytest.mark.container
def test_cbr_carries_an_info_tag_and_vbr_a_xing_tag_and_the_average_is_not_a_setting(built) -> None:
    cbr, vbr = built["mp3/128kbps-30s.mp3"], built["mp3/vbr-v2-30s.mp3"]
    assert b"Info" in cbr[: first_frame(cbr) + 64] and b"Xing" not in cbr[:400]
    assert b"Xing" in vbr[: first_frame(vbr) + 64], "the variable-bitrate marker"
    average = props_of("mp3/vbr-v2-30s.mp3", vbr)["bitrate_kbps"]
    assert average == 48.2 and average not in (128.0, 320.0)
    assert "48.2 kbps" in CATALOG.by_path["mp3/vbr-v2-30s.mp3"].description


@pytest.mark.container
def test_the_22_khz_mono_file_is_mpeg_2_layer_3_and_refused_as_stereo(built, tmp_path) -> None:
    path = "mp3/mono-22khz-64kbps-30s.mp3"
    data = built[path]
    header = data[first_frame(data) : first_frame(data) + 4]
    assert (header[1] >> 3) & 0b11 == 0b10, "MPEG version 2, the 22.05 kHz family"
    assert (header[1] >> 1) & 0b11 == 0b01, "Layer III"
    assert (header[3] >> 6) == 0b11, "channel mode: single channel"
    stereo = build(path, tmp_path, channels=2)
    assert any("channels" in f for f in failures(path, stereo))


# --- wav: what the header says, read without ffprobe -----------------------------------------


def header(data: bytes) -> dict[str, Any]:
    """channels, rate, bits, format tag and frames from the `fmt ` and `data` chunks alone."""
    offset, fmt, size = 12, None, None
    while offset + 8 <= len(data):
        chunk, length = (
            data[offset : offset + 4],
            struct.unpack("<I", data[offset + 4 : offset + 8])[0],
        )
        if chunk == b"fmt ":
            fmt = struct.unpack("<HHIIHH", data[offset + 8 : offset + 24])
        if chunk == b"data":
            size = length
            break
        offset += 8 + length + (length & 1)
    assert fmt is not None and size is not None
    tag, channels, rate, _per_second, block, bits = fmt
    frames = size // block
    return {
        "tag": tag,
        "channels": channels,
        "sample_rate": rate,
        "bit_depth": bits,
        "frames": frames,
        "duration_ms": frames * 1000 / rate,
    }


def test_the_four_props_the_scoreboard_compares_are_what_the_header_says_for_the_four_rows(
    built, tmp_path
) -> None:
    for path in WAV:
        data = built.get(path) or build(path, tmp_path / "100mb")
        said, props = header(data), MANIFEST[path]["props"]
        for name in ("channels", "sample_rate", "bit_depth"):
            assert props[name] == said[name], (path, name)
        assert abs(props["duration_ms"] - said["duration_ms"]) <= 1, (path, said)
        assert path != "wav/100mb.wav" or len(data) == 100_000_000


def test_the_header_reader_here_would_notice_a_wrong_prop() -> None:
    """The control: held against a manifest value that is off by a sample rate, it disagrees."""
    one_second = struct.pack("<HHIIHH", 1, 1, 8000, 8000, 1, 8)
    data = b"RIFF" + struct.pack("<I", 0) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + one_second
    data += b"data" + struct.pack("<I", 8000) + bytes(8000)
    said = header(data)
    assert (said["sample_rate"], said["duration_ms"]) == (8000, 1000.0)
    assert said["sample_rate"] != 44100 and abs(1000 - said["duration_ms"] * 8) > 1


@pytest.mark.container
def test_8_khz_mono_is_unsigned_eight_bit_at_8000_and_refused_at_the_cd_rate(built, tmp_path):
    path = "wav/sine-440hz-3s-8k-8bit-mono.wav"
    data = built[path]
    assert len(data) == 24_044 and _wav_header(data) == {"header_format": "pcm", "header_bytes": 44}
    # Unsigned 8-bit is centred on 128: a sine's samples straddle it. Read as signed, the same
    # bytes would sit near -128 and never cross zero.
    samples = data[44:]
    assert min(samples) < 128 < max(samples) and abs(sum(samples) / len(samples) - 128) < 2
    assert all(96 <= value <= 160 for value in samples), "a quiet sine around the centre"
    cd = build(path, tmp_path, sample_rate=44100)
    assert any("sample_rate" in f for f in failures(path, cd))


@pytest.mark.container
def test_96_khz_float_is_tag_3_with_a_fact_chunk_and_eight_bytes_a_frame(built, tmp_path) -> None:
    path = "wav/sine-440hz-3s-96k-32bit-float.wav"
    data = built[path]
    assert _wav_header(data) == {"header_format": "float", "header_bytes": 58}
    assert data[38:42] == b"fact" and len(data) == 58 + 288_000 * 8 == 2_304_058
    said = header(data)
    assert (said["tag"], said["channels"], said["frames"]) == (3, 2, 288_000)
    # What Java 8 reports for it (2026-11-14, Temurin 8.0.512): the frame count taken in bytes,
    # eight times the 3 seconds the header's data chunk holds. Held here as the arithmetic that
    # explains it, so a scoreboard cell that says 24000 can be checked against the file.
    assert (len(data) - 58) / said["sample_rate"] == 24.0 and said["duration_ms"] == 3000.0
    extensible = REGISTRY.get("media_audio.pcm")(
        GeneratorContext(path=path, workdir=tmp_path), duration=3, sample_rate=96000, bits=32
    )
    assert _wav_header(extensible)["header_format"] == "extensible"
    assert failures(path, extensible), "ffmpeg's own float header is a different file"


@pytest.mark.container
def test_silence_is_all_zero_samples_and_a_sine_in_its_place_is_not(built, tmp_path) -> None:
    path = "wav/silence-5s.wav"
    data = built[path]
    assert len(data) == 882_044 and data[44:] == bytes(882_000)
    assert "tone_hz" not in props_of(path, data)
    sine = build(path, tmp_path, source="sine")
    assert sine[44:] != bytes(882_000) and props_of(path, sine)["tone_hz"] == [440.0, 440.0]


def test_the_100_mb_wav_is_exact_and_its_arithmetic_is_the_manifests(tmp_path) -> None:
    props = MANIFEST["wav/100mb.wav"]["props"]
    assert MANIFEST["wav/100mb.wav"]["bytes"] == 100_000_000
    frames = (100_000_000 - media_audio.WAV_HEADER_BYTES) // 4
    assert frames == 24_999_989 and (100_000_000 - 44) % 4 == 0
    assert props["duration_ms"] == round(frames * 1000 / 44100) == 566_893
    odd = REGISTRY.get("media_audio.wav_sized")
    with pytest.raises(Exception, match="cannot be an exact WAV"):
        odd(GeneratorContext(path="wav/x.wav", workdir=tmp_path), size=100_000_001)


# --- flac -----------------------------------------------------------------------------------


def streaminfo(data: bytes) -> dict[str, int]:
    """Sample rate, channels and bits per sample from FLAC's STREAMINFO block, byte by byte."""
    assert data[:4] == b"fLaC" and data[4] & 0x7F == 0, "the first block is STREAMINFO"
    block = data[8:42]
    packed = int.from_bytes(block[10:18], "big")
    return {
        "sample_rate": packed >> 44,
        "channels": ((packed >> 41) & 0b111) + 1,
        "bit_depth": ((packed >> 36) & 0b11111) + 1,
    }


@pytest.mark.container
def test_the_flac_declares_24_bits_at_96_khz_and_the_default_is_16(built, tmp_path) -> None:
    path = "flac/24bit-96k-10s.flac"
    assert streaminfo(built[path]) == {"sample_rate": 96000, "channels": 2, "bit_depth": 24}
    assert props_of(path, built[path])["bit_depth"] == 24
    plain = build(path, tmp_path, bits=None)
    assert streaminfo(plain)["bit_depth"] == 16
    assert any("bit_depth" in f for f in failures(path, plain)), "refused without its difference"


def test_flac_bit_depth_is_published_only_where_it_is_not_16(tmp_path) -> None:
    """So no published entry changed: the older FLAC file has no `bit_depth`."""
    assert "bit_depth" not in MANIFEST["flac/sine-440hz-30s.flac"]["props"]
    assert MANIFEST["flac/24bit-96k-10s.flac"]["props"]["bit_depth"] == 24
    encoded = REGISTRY.get("media_audio.encoded")
    context = GeneratorContext(path="flac/x.flac", workdir=tmp_path)
    with pytest.raises(ValueError, match="only 24 is built"):
        encoded(context, codec="flac", duration=1, bits=16)
    with pytest.raises(ValueError, match="only asked of FLAC"):
        encoded(context, codec="mp3", duration=1, bits=24)


# --- nothing published moved ----------------------------------------------------------------


@pytest.mark.container
def test_the_published_audio_rows_still_build_to_their_published_bytes(tmp_path) -> None:
    """The generator gained a source and a parameter; no existing command may have changed."""
    rows = [
        p
        for p, e in MANIFEST.items()
        if e["format"] in AUDIO_FORMATS
        and e["generator"].startswith("media_audio.")
        and e["added_in"] != "1.16.0"
        and e["bytes"] < 2_500_000
        and not CATALOG.by_path[p].expected_drift
        and not CATALOG.by_path[p].depends_on
    ]
    assert len(rows) >= 14 and "mp3/stereo-lr-5s.mp3" in rows and "wav/silence-5s.wav" not in rows
    for index, path in enumerate(rows):
        data = build(path, tmp_path / str(index))
        assert hashlib.sha256(data).hexdigest() == MANIFEST[path]["sha256"], path


# --- aliases --------------------------------------------------------------------------------


def test_ogv_and_ts_have_aliases_with_their_originals_bytes() -> None:
    aliases = yaml.safe_load((ROOT / "catalog" / "_aliases.yaml").read_text())["aliases"]
    assert aliases["ogv"] == "ogv/720p-5s.ogv" and aliases["ts"] == "ts/720p-5s.ts"
    for fmt, original in (("ogv", "ogv/720p-5s.ogv"), ("ts", "ts/720p-5s.ts")):
        alias = MANIFEST[f"{fmt}/sample.{fmt}"]
        assert alias["generator"] == "alias.copy" and alias["generator_params"] == {"of": original}
        assert alias["sha256"] == MANIFEST[original]["sha256"]
        assert (
            alias["bytes"] == MANIFEST[original]["bytes"] and 2_000_000 < alias["bytes"] < 4_000_000
        )
    assert "opus/sample.opus" not in MANIFEST, "both its files are expected_drift"
