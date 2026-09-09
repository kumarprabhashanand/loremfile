"""M3.6 media: generators, validators, negative tests, determinism tests.

The spike that preceded this milestone ran every encoder twice in separate processes and
again in a later invocation minutes apart — the second check being the one that caught
openpyxl in M3.5, where same-invocation runs agreed and different invocations did not.
All fifteen recipes reproduced byte for byte, so ffmpeg's bit-exact flags and mutagen
both hold, and docs/06 §4 now says so with dates.

What the encoders cannot be trusted about is what a *player* needs, which is what the
tests below check: that `moov` precedes `mdat`, that an HLS playlist names its segments
relatively and ends, and that a sized WAV is exactly the size it claims.
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import pytest
from mutagen.id3 import ID3

from loremfile import build as build_module
from loremfile.build import load_generators
from loremfile.catalog import Catalog, Fixture
from loremfile.generators import media_audio
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.util.ffmpeg import run
from loremfile.util.sizing import SizingError
from loremfile.validators import _REGISTRY, ValidationError, load, validate
from loremfile.validators.media import _atoms

WORKDIR = Path(tempfile.mkdtemp())
CATALOG = Catalog.load()
load_generators()
load()

MEDIA_FORMATS = {
    "mp4", "webm", "mkv", "mov", "avi", "ogv", "ts", "hls",
    "mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "aiff",
}  # fmt: skip


def fixture(path: str) -> Fixture:
    return CATALOG.by_path[path]


def built(path: str) -> bytes:
    """Media fixtures are far too slow to regenerate per test; read the build output.

    ci.yml runs `build` before pytest, so this is the same byte sequence the validators
    ran against — and the determinism proof lives in `test_determinism.py`, which does
    regenerate, twice, for the proving fixtures only.
    """
    target = build_module.fixtures_dir() / path
    if not target.is_file():
        pytest.skip(f"run `loremfile build --only {path}` first")
    return target.read_bytes()


def measure(path: str, payload: bytes) -> dict:
    entry = fixture(path)
    return _REGISTRY[entry.format](payload, entry, CATALOG.mime_for(entry))


def generate(path: str) -> bytes:
    entry = fixture(path)
    context = GeneratorContext(path=path, workdir=WORKDIR)
    context._dependency = built
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **entry.params)
    return out if isinstance(out, bytes) else out.read_bytes()


EVERY_MEDIA_FIXTURE = [p for p, f in CATALOG.by_path.items() if f.format in MEDIA_FORMATS]


@pytest.mark.parametrize("path", EVERY_MEDIA_FIXTURE)
def test_every_media_fixture_matches_its_catalog_entry(path: str) -> None:
    entry = fixture(path)
    report = validate(built(path), entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures


# --- what a player needs and a parser will not tell you ---------------------


@pytest.mark.parametrize("path", ["mp4/720p-5s.mp4", "mov/720p-5s.mov"])
def test_moov_comes_before_mdat(path: str) -> None:
    """Without +faststart the file plays from disk and stalls when streamed."""
    order = _atoms(built(path))
    assert "moov" in order and "mdat" in order, order
    assert order.index("moov") < order.index("mdat"), order


def tiny_mp4(*, faststart: bool, video: bool = True, seconds: float = 5) -> bytes:
    """A real, ffprobe-readable MP4, encoded as small as possible for the controls below.

    Hand-built boxes were the obvious shortcut here and the wrong one: the validator
    probes before it inspects the box order, so a synthetic file fails as unreadable and
    proves nothing about the check under test. These have to be files ffprobe accepts.
    """
    target = WORKDIR / f"tiny-{faststart}-{video}-{seconds}.mp4"
    args = []
    if video:
        args += ["-f", "lavfi", "-i", "testsrc2=size=128x72:rate=10"]
    args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", f"{seconds:g}"]
    if video:
        args += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-x264-params",
            "threads=1",
        ]
    args += ["-c:a", "aac", "-b:a", "64k"]
    if faststart:
        args += ["-movflags", "+faststart"]
    run([*args, "-f", "mp4", str(target)])
    return target.read_bytes()


def test_a_file_with_moov_last_is_rejected() -> None:
    """The negative control: a real MP4 encoded without +faststart must be refused.

    ffprobe reads it happily and it plays fine from disk. Only the box order says it
    would stall a progressive player, which is the whole reason the check exists.
    """
    without = tiny_mp4(faststart=False)
    assert _atoms(without).index("moov") > _atoms(without).index("mdat"), (
        "ffmpeg now writes moov first without being asked; the check and docs/05 §3.3 "
        "should both be revisited if that is permanent"
    )
    with pytest.raises(ValidationError, match="faststart"):
        measure("mp4/720p-5s.mp4", without)

    # And the same encode *with* the flag passes, so the test is not just rejecting
    # everything the helper produces.
    assert measure("mp4/720p-5s.mp4", tiny_mp4(faststart=True))["video_streams"] == 1


def test_the_hls_playlist_names_its_segments_relatively() -> None:
    """ffmpeg emits the absolute path it was given; a published playlist cannot."""
    text = built("hls/720p-10s/index.m3u8").decode("utf-8")
    uris = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    assert uris == [f"seg-{index:03d}.ts" for index in range(len(uris))], uris
    assert "/" not in "".join(uris)
    assert "#EXT-X-ENDLIST" in text


def test_a_playlist_with_absolute_uris_is_rejected() -> None:
    bad = b"#EXTM3U\n#EXT-X-TARGETDURATION:2\n/build/fixtures/seg-000.ts\n#EXT-X-ENDLIST\n"
    with pytest.raises(ValidationError, match="relative"):
        measure("hls/720p-10s/index.m3u8", bad)


def test_a_playlist_without_endlist_is_rejected() -> None:
    """A VOD playlist missing ENDLIST is read as a live stream that never finishes."""
    bad = b"#EXTM3U\n#EXT-X-TARGETDURATION:2\nseg-000.ts\n"
    with pytest.raises(ValidationError, match="EXT-X-ENDLIST"):
        measure("hls/720p-10s/index.m3u8", bad)


def test_every_hls_segment_is_a_real_transport_stream() -> None:
    segments = [p for p in EVERY_MEDIA_FIXTURE if p.endswith(".ts") and p.startswith("hls/")]
    assert len(segments) == 5, segments
    for path in segments:
        props = measure(path, built(path))
        assert props["video_streams"] == 1, path


# --- sizing -----------------------------------------------------------------


def test_the_sized_wav_is_exact_to_the_byte() -> None:
    """`exact` means exact: 44 bytes of header plus a whole number of frames."""
    data = built("wav/10mb.wav")
    assert len(data) == 10_000_000
    (riff_size,) = struct.unpack("<I", data[4:8])
    (data_size,) = struct.unpack("<I", data[40:44])
    assert riff_size == len(data) - 8
    assert data_size == len(data) - 44
    assert data_size % 4 == 0, "16-bit stereo frames are 4 bytes"


def test_a_size_that_is_not_a_whole_number_of_frames_is_refused() -> None:
    """Better to fail the build than to publish a WAV whose header lies by a byte."""
    context = GeneratorContext(path="wav/x.wav", workdir=WORKDIR)
    with pytest.raises(SizingError, match="whole number"), deterministic(context.seed):
        media_audio.wav_sized(context, size=10_000_003, sample_rate=44100, bits=16, channels=2)


# --- tags -------------------------------------------------------------------


def test_id3_tags_are_fixed_values_with_no_build_timestamp() -> None:
    path = build_module.fixtures_dir() / "mp3/with-id3v2-tags-3s.mp3"
    if not path.is_file():
        pytest.skip("run `loremfile build --only mp3/with-id3v2-tags-3s.mp3` first")
    tags = ID3(path)
    assert str(tags["TIT2"]) == "Loremfile Test Tone"
    assert str(tags["TPE1"]) == "loremfile.dev"
    assert str(tags["TDRC"]) == "2020", "the year is the catalog's literal, not the build date"
    assert not [key for key in tags if key.startswith("TDEN") or key.startswith("TDTG")], (
        "mutagen wrote an encoding or tagging timestamp; those move between builds"
    )


def test_the_cover_art_is_the_published_png() -> None:
    """Not a regenerated lookalike — the bytes that were actually published."""
    path = build_module.fixtures_dir() / "mp3/with-id3v2-tags-3s.mp3"
    if not path.is_file():
        pytest.skip("run `loremfile build --only mp3/with-id3v2-tags-3s.mp3` first")
    covers = ID3(path).getall("APIC")
    assert len(covers) == 1
    assert covers[0].data == built("png/100x100.png")
    assert covers[0].mime == "image/png"


# --- validator negative controls -------------------------------------------


def test_truncated_media_is_rejected() -> None:
    data = built("mp3/sine-440hz-3s.mp3")
    with pytest.raises(ValidationError):
        measure("mp3/sine-440hz-3s.mp3", data[:200] + b"\x00" * 50)


def test_a_video_with_no_video_stream_is_rejected() -> None:
    """An audio-only file in an MP4 container probes fine and is not a video fixture.

    It has to be five seconds long: the duration check runs first, and a thirty-second
    file would be rejected for the wrong reason — which is how this test first passed
    while proving nothing.
    """
    with pytest.raises(ValidationError, match="no video stream"):
        measure("mp4/720p-5s.mp4", tiny_mp4(faststart=True, video=False, seconds=5))


def test_duration_is_checked_against_the_catalog() -> None:
    """A five-second fixture holding thirty seconds of audio must not pass."""
    with pytest.raises(ValidationError, match="catalog asks for"):
        measure("mp3/stereo-lr-5s.mp3", built("mp3/sine-440hz-30s.mp3"))
