"""Video fixtures: mp4, webm, mkv, mov, avi, ogv, ts (docs/05 §3.3).

Every fixture is `testsrc2` — ffmpeg's synthetic test pattern — plus a 440 Hz sine, so
nothing here is derived from anyone's footage. The bit-exact flags live in
`util.ffmpeg`; single-threaded encoding is not a performance oversight but the reason
two builds agree, because multi-threaded x264 and VP9 both make timing-dependent
slice decisions.

The sized fixtures use a two-pass encode with the rate held flat (`-b:v`, `-minrate`
and `-maxrate` equal, `-bufsize` twice that), which is what makes a target size
reachable analytically rather than by search: bytes are bitrate x seconds / 8.
"""

from __future__ import annotations

from pathlib import Path

from loremfile.config import APPROX_TOLERANCE
from loremfile.generators.base import GeneratorContext, generator
from loremfile.util.ffmpeg import encoder_for, run
from loremfile.util.sizing import fit

#: The audio track every video carries unless the catalog says `audio: false`.
AUDIO_SOURCE = "sine=frequency=440:sample_rate=48000"
AUDIO_BITRATE = "128k"
AUDIO_BITS_PER_SECOND = 128_000

#: x264 settings from docs/05 §3.3. `threads=1` is repeated inside `-x264-params`
#: because the global `-threads 1` does not reach the encoder's own thread pool.
X264_ARGS = ("-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", "-x264-params", "threads=1")


def _inputs(width: int, height: int, fps: int, duration: float, audio: bool) -> list[str]:
    args = ["-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}"]
    if audio:
        args += ["-f", "lavfi", "-i", AUDIO_SOURCE]
    return [*args, "-t", f"{duration:g}"]


def _target(ctx: GeneratorContext, suffix: str) -> Path:
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    return ctx.workdir / f"{ctx.path.replace('/', '_')}{suffix}"


def _encode(ctx: GeneratorContext, suffix: str, args: list[str]) -> bytes:
    target = _target(ctx, suffix)
    run([*args, str(target)])
    return target.read_bytes()


@generator(parallel_safe=False)
def mp4(
    ctx: GeneratorContext,
    *,
    width: int,
    height: int,
    duration: float,
    fps: int = 30,
    audio: bool = True,
    profile: str | None = None,
    level: str | None = None,
    container: str = "mp4",
) -> bytes:
    """H.264 video with AAC audio in MP4, MOV or MPEG-TS."""
    args = _inputs(width, height, fps, duration, audio)
    args += ["-c:v", encoder_for("h264"), *X264_ARGS]
    if profile:
        args += ["-profile:v", profile]
    if level:
        args += ["-level", level]
    args += ["-c:a", encoder_for("aac"), "-b:a", AUDIO_BITRATE] if audio else ["-an"]
    if container in {"mp4", "mov"}:
        # Puts the moov atom first so a player can start before the file has arrived.
        args += ["-movflags", "+faststart"]
    suffix = {"mp4": ".mp4", "mov": ".mov", "mpegts": ".ts", "matroska": ".mkv"}[container]
    args += ["-f", container]
    return _encode(ctx, suffix, args)


@generator(parallel_safe=False)
def webm(
    ctx: GeneratorContext,
    *,
    width: int,
    height: int,
    duration: float,
    fps: int = 30,
    bitrate: str = "1M",
) -> bytes:
    """VP9 video with Opus audio. `-row-mt 0` keeps the encode single-threaded."""
    args = _inputs(width, height, fps, duration, audio=True)
    args += [
        "-c:v",
        encoder_for("vp9"),
        "-b:v",
        bitrate,
        "-row-mt",
        "0",
        "-threads",
        "1",
        "-deadline",
        "good",
        "-cpu-used",
        "2",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        encoder_for("opus"),
        "-b:a",
        "96k",
        "-f",
        "webm",
    ]
    return _encode(ctx, ".webm", args)


@generator(parallel_safe=False)
def avi(ctx: GeneratorContext, *, width: int, height: int, duration: float, fps: int = 30) -> bytes:
    """MPEG-4 Part 2 video with MP3 audio — the combination AVI files actually carry."""
    args = _inputs(width, height, fps, duration, audio=True)
    args += [
        "-c:v",
        "mpeg4",
        "-q:v",
        "5",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        encoder_for("mp3"),
        "-b:a",
        AUDIO_BITRATE,
        "-f",
        "avi",
    ]
    return _encode(ctx, ".avi", args)


@generator(parallel_safe=False)
def ogv(ctx: GeneratorContext, *, width: int, height: int, duration: float, fps: int = 30) -> bytes:
    """Theora video with Vorbis audio in Ogg."""
    args = _inputs(width, height, fps, duration, audio=True)
    args += [
        "-c:v",
        encoder_for("theora"),
        "-q:v",
        "7",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        encoder_for("vorbis"),
        "-q:a",
        "4",
        "-f",
        "ogv",
    ]
    return _encode(ctx, ".ogv", args)


@generator(parallel_safe=False)
def mp4_sized(
    ctx: GeneratorContext,
    *,
    size: int,
    duration: float,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
) -> bytes:
    """An MP4 of about ``size`` bytes at a fixed duration (docs/05 §6).

    Two passes, with the rate held flat so the result lands near the analytic bitrate on
    the first attempt. `fit` is still in the loop because muxer overhead and the final
    GOP make the mapping from bitrate to bytes only approximately linear — but it starts
    from a computed value, not a guess, so it converges in a step or two.
    """
    passlog = _target(ctx, ".passlog")

    def make(bits_per_second: int) -> bytes:
        target = _target(ctx, ".mp4")
        rate = [
            "-b:v",
            str(bits_per_second),
            "-minrate",
            str(bits_per_second),
            "-maxrate",
            str(bits_per_second),
            "-bufsize",
            str(bits_per_second * 2),
        ]
        common = [
            *_inputs(width, height, fps, duration, audio=True),
            "-c:v",
            encoder_for("h264"),
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-x264-params",
            "threads=1",
            *rate,
            "-passlogfile",
            str(passlog),
        ]
        run([*common, "-pass", "1", "-an", "-f", "null", "-"])
        run(
            [
                *common,
                "-pass",
                "2",
                "-c:a",
                encoder_for("aac"),
                "-b:a",
                AUDIO_BITRATE,
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                str(target),
            ]
        )
        return target.read_bytes()

    # docs/05 §6 originally discounted this by 0.97 to leave room for muxer overhead.
    # Measured, the overhead is far smaller than that, and the discount put 1mb.mp4 at
    # 4.85% under target — inside the 5% tolerance, but one encoder change away from
    # failing the build. The analytic value is used undiscounted and `fit` corrects what
    # is left; §6 records the measurement.
    start = round(size * 8 / duration - AUDIO_BITS_PER_SECOND)
    _, payload = fit(size, APPROX_TOLERANCE, make, n0=start, n_min=10_000, n_max=200_000_000)
    return payload
