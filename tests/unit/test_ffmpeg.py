"""M1.7: the ffmpeg wrapper's flags and encoder map (docs/06 §4).

The encoder names were verified against the pinned image in M1.2. The tests that shell
out are marked ``container`` because they are only meaningful inside that image.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from loremfile.util import ffmpeg

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg is only in the toolchain image")


def test_global_flags_are_the_ones_that_belong_before_the_input() -> None:
    flags = ffmpeg.GLOBAL_FLAGS
    # One thread: multi-threaded encoders make timing-dependent choices.
    assert flags[flags.index("-threads") + 1] == "1"
    assert "-y" in flags and "-nostdin" in flags
    # Output-only options must not be here: before -i they would apply to the input.
    assert "-map_metadata" not in flags
    assert "-metadata" not in flags


def test_output_flags_cover_what_makes_output_drift() -> None:
    flags = ffmpeg.OUTPUT_FLAGS
    assert flags[flags.index("-map_metadata") + 1] == "-1"
    assert flags[flags.index("-fflags") + 1] == "+bitexact"
    assert flags[flags.index("-flags:v") + 1] == "+bitexact"
    assert flags[flags.index("-flags:a") + 1] == "+bitexact"
    assert flags[flags.index("-metadata") + 1] == "encoder="


def test_output_flags_are_spliced_before_the_output_not_the_input(monkeypatch) -> None:
    """ffmpeg's grammar is positional, so placement is the whole point."""
    seen: dict[str, list[str]] = {}

    class Done:
        returncode = 0
        stderr = b""

    def fake_run(command, **kwargs):  # noqa: ARG001
        seen["command"] = command
        return Done()

    monkeypatch.setattr(ffmpeg, "tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)
    ffmpeg.run(["-f", "lavfi", "-i", "sine=duration=1", "out.wav"])

    command = seen["command"]
    assert command[-1] == "out.wav"
    assert command.index("-i") < command.index("-map_metadata")
    assert command.index("-map_metadata") < command.index("out.wav")


def test_run_needs_an_output_path() -> None:
    with pytest.raises(ffmpeg.FfmpegError, match="at least an output path"):
        ffmpeg.run([])


@pytest.mark.parametrize(
    ("codec", "expected"),
    [
        ("h264", "libx264"),
        ("hevc", "libx265"),
        ("vp8", "libvpx"),
        ("vp9", "libvpx-vp9"),
        ("av1", "libsvtav1"),
        ("theora", "libtheora"),
        ("prores", "prores_ks"),
        ("mp3", "libmp3lame"),
        ("opus", "libopus"),
        ("vorbis", "libvorbis"),
    ],
)
def test_encoder_names_match_what_the_image_provides(codec: str, expected: str) -> None:
    """M1.2 found the docs said 'theora' and 'prores'; the real names differ."""
    assert ffmpeg.encoder_for(codec) == expected


def test_unknown_codec_lists_the_known_ones() -> None:
    with pytest.raises(ffmpeg.FfmpegError, match="no encoder recorded"):
        ffmpeg.encoder_for("realaudio")


def test_missing_tool_explains_that_media_needs_the_image() -> None:
    with pytest.raises(ffmpeg.FfmpegError, match="toolchain image"):
        ffmpeg.tool("definitely-not-a-real-binary")


@pytest.mark.container
@needs_ffmpeg
def test_every_mapped_encoder_exists_in_this_image() -> None:
    available = ffmpeg.available_encoders()
    missing = sorted(set(ffmpeg.ENCODERS.values()) - available)
    assert not missing, f"encoders missing from the image: {missing}"


@pytest.mark.container
@needs_ffmpeg
def test_run_produces_identical_bytes_twice(tmp_path: Path) -> None:
    """The whole reason the wrapper exists: two runs, one sha256."""
    outputs = []
    for index in (1, 2):
        target = tmp_path / f"out{index}.wav"
        ffmpeg.run(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1:sample_rate=8000",
                "-c:a",
                "pcm_s16le",
                str(target),
            ]
        )
        outputs.append(target.read_bytes())
    assert outputs[0] == outputs[1]


@pytest.mark.container
@needs_ffmpeg
def test_probe_reads_back_what_was_written(tmp_path: Path) -> None:
    target = tmp_path / "probe.wav"
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1:sample_rate=8000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ]
    )
    info = ffmpeg.probe(target)
    stream = info["streams"][0]
    assert stream["codec_name"] == "pcm_s16le"
    assert int(stream["sample_rate"]) == 8000


@pytest.mark.container
@needs_ffmpeg
def test_failure_carries_the_stderr_tail() -> None:
    with pytest.raises(ffmpeg.FfmpegError, match="ffmpeg exited"):
        ffmpeg.run(["-i", "no-such-input.wav", "/tmp/never-written.wav"])  # noqa: S108
