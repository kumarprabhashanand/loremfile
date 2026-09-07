"""ffmpeg and ffprobe wrappers that produce bit-exact output (docs/06 §4).

Every media generator goes through :func:`run`. ffmpeg otherwise stamps its own version
into the container, threads work nondeterministically, and encoders make
timing-dependent choices — all of which would make a fixture's sha256 drift between
builds and break the immutability promise.

Encoder names are the ones the pinned image actually provides, verified in M1.2:
the Theora encoder is ``libtheora`` (not ``theora``) and ProRes means ``prores_ks``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

#: Options that must appear *before* the input, because ffmpeg reads them globally.
GLOBAL_FLAGS = (
    "-hide_banner",
    "-nostdin",
    "-y",
    "-threads",
    "1",
)

#: Options that must appear immediately *before the output file*. ffmpeg's grammar is
#: positional: an option before ``-i`` applies to the input, so putting these first
#: silently changes what they mean — and with ``-f lavfi`` it fails outright.
#: ``+bitexact`` and the emptied encoder tag stop ffmpeg writing its version and build
#: stamps into the container, which is what makes two builds hash the same.
OUTPUT_FLAGS = (
    "-map_metadata",
    "-1",
    "-fflags",
    "+bitexact",
    "-flags:v",
    "+bitexact",
    "-flags:a",
    "+bitexact",
    "-metadata",
    "encoder=",
)

#: The encoder names the pinned image provides for each codec (verified in M1.2).
ENCODERS = {
    "h264": "libx264",
    "hevc": "libx265",
    "vp8": "libvpx",
    "vp9": "libvpx-vp9",
    "av1": "libsvtav1",
    "theora": "libtheora",
    "prores": "prores_ks",
    "aac": "aac",
    "flac": "flac",
    "mp3": "libmp3lame",
    "opus": "libopus",
    "vorbis": "libvorbis",
}


#: ``ffmpeg -encoders`` prints a six-character capability field, then the encoder name.
_CAPABILITY_FIELD_WIDTH = 6
_MIN_ENCODER_LINE_FIELDS = 2


class FfmpegError(RuntimeError):
    """ffmpeg or ffprobe failed. Carries the tail of stderr, which is the useful part."""


def tool(name: str) -> str:
    """Absolute path to a toolchain binary, or a clear error naming the image."""
    found = shutil.which(name)
    if found is None:
        raise FfmpegError(
            f"{name} is not on PATH. Media generators only run inside the toolchain "
            "image (tools/TOOLCHAIN_DIGEST); host output would differ anyway."
        )
    return found


def encoder_for(codec: str) -> str:
    """The ffmpeg encoder name for a codec, so generators never guess."""
    try:
        return ENCODERS[codec]
    except KeyError:
        known = ", ".join(sorted(ENCODERS))
        raise FfmpegError(f"no encoder recorded for '{codec}'; known: {known}") from None


def run(args: list[str], *, cwd: Path | None = None, timeout: int = 600) -> None:
    """Run ffmpeg with the bit-exact flags in their correct positions.

    ``args`` is everything between the global options and the output path, ending with
    the output path itself. The output flags are spliced in just before that last
    argument, because ffmpeg applies an option to whichever file follows it.
    """
    if not args:
        raise FfmpegError("run() needs at least an output path")
    *leading, output = args
    command = [tool("ffmpeg"), *GLOBAL_FLAGS, *leading, *OUTPUT_FLAGS, output]
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, paths we built
        command, cwd=cwd, capture_output=True, timeout=timeout, check=False
    )
    if completed.returncode != 0:
        tail = completed.stderr.decode("utf-8", "replace").strip().splitlines()[-20:]
        raise FfmpegError(f"ffmpeg exited {completed.returncode}\n  " + "\n  ".join(tail))


def probe(path: Path, *, timeout: int = 120) -> dict[str, Any]:
    """``ffprobe -show_streams -show_format`` as a dict. Used by the media validators."""
    command = [
        tool("ffprobe"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        command, capture_output=True, timeout=timeout, check=False
    )
    if completed.returncode != 0:
        tail = completed.stderr.decode("utf-8", "replace").strip()
        raise FfmpegError(f"ffprobe exited {completed.returncode}: {tail}")
    parsed: dict[str, Any] = json.loads(completed.stdout)
    return parsed


def available_encoders() -> set[str]:
    """Encoder names the installed ffmpeg offers. Used by the toolchain smoke test."""
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [tool("ffmpeg"), "-hide_banner", "-encoders"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise FfmpegError("could not list ffmpeg encoders")
    names: set[str] = set()
    for line in completed.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split()
        # Lines look like " V....D libx264   libx264 H.264 / AVC ..."
        if (
            len(parts) >= _MIN_ENCODER_LINE_FIELDS
            and len(parts[0]) == _CAPABILITY_FIELD_WIDTH
            and not line.startswith(" ---")
        ):
            names.add(parts[1])
    return names
