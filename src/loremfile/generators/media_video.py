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

import struct
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


def _inputs(
    width: int, height: int, fps: int, duration: float, audio: bool, effects: str = ""
) -> list[str]:
    args = ["-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}{effects}"]
    if audio:
        args += ["-f", "lavfi", "-i", AUDIO_SOURCE]
    return [*args, "-t", f"{duration:g}"]


def _x264_args(asm: str | None) -> list[str]:
    """X264_ARGS, with `asm=` appended to the one `-x264-params` value when it is pinned."""
    args = list(X264_ARGS)
    if asm:
        at = args.index("-x264-params") + 1
        args[at] = f"{args[at]}:asm={asm}"
    return args


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
    faststart: bool = True,
    rotation: int = 0,
    x264_asm: str | None = None,
) -> bytes:
    """H.264 video with AAC audio in MP4, MOV or MPEG-TS.

    `rotation` is the clockwise turn, in degrees, that the video track's display matrix asks
    a player to apply. The encode is the unrotated one, byte for byte: only the matrix moves.
    `x264_asm` names the instruction sets x264 may use (`asm=` in `-x264-params`), which
    pins the kernels it would otherwise pick from the CPU it finds (docs/06 §4).
    """
    args = _inputs(width, height, fps, duration, audio)
    args += ["-c:v", encoder_for("h264"), *_x264_args(x264_asm)]
    if profile:
        args += ["-profile:v", profile]
    if level:
        args += ["-level", level]
    args += ["-c:a", encoder_for("aac"), "-b:a", AUDIO_BITRATE] if audio else ["-an"]
    if container in {"mp4", "mov"} and faststart:
        # Puts the moov atom first so a player can start before the file has arrived.
        args += ["-movflags", "+faststart"]
    suffix = {"mp4": ".mp4", "mov": ".mov", "mpegts": ".ts", "matroska": ".mkv"}[container]
    args += ["-f", container]
    data = _encode(ctx, suffix, args)
    return set_rotation(data, rotation) if rotation else data


#: A display matrix (ISO/IEC 14496-12 §8.3.2) is nine 32-bit values, a b u / c d v / x y w.
#: a, b, c and d are 16.16 fixed point and w is 2.30, so 0x10000 is 1 and 0x40000000 is 1.
UNIT, UNIT_W = 0x10000, 0x40000000
ROTATION_MATRICES = {
    90: (0, UNIT, 0, -UNIT, 0, 0, 0, 0, UNIT_W),
    180: (-UNIT, 0, 0, 0, -UNIT, 0, 0, 0, UNIT_W),
    270: (0, -UNIT, 0, UNIT, 0, 0, 0, 0, UNIT_W),
}
BOX_HEADER_BYTES = 8
#: Where the matrix sits in a `tkhd` box's payload: after the version and flags, the
#: creation and modification times, the track id, a reserved word and the duration (32-bit
#: fields in version 0, with 64-bit times and duration in version 1), then 16 bytes more.
TKHD_MATRIX_OFFSET = {0: 4 + 20 + 16, 1: 4 + 32 + 16}


def _boxes(data: bytes | bytearray, start: int, end: int) -> list[tuple[bytes, int, int]]:
    """(name, payload start, box end) for each box between `start` and `end`."""
    found, offset = [], start
    while offset + BOX_HEADER_BYTES <= end:
        (size,) = struct.unpack_from(">I", data, offset)
        name, header = bytes(data[offset + 4 : offset + 8]), BOX_HEADER_BYTES
        if size == 1:
            (size,) = struct.unpack_from(">Q", data, offset + 8)
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            raise ValueError(f"the {name!r} box at byte {offset} does not fit its parent")
        found.append((name, offset + header, offset + size))
        offset += size
    return found


def set_rotation(data: bytes, degrees: int) -> bytes:
    """The same MP4 with the video track's display matrix turned `degrees` clockwise.

    ffmpeg 5.1 cannot write it: `-display_rotation` arrives in 6.0 and the muxer ignores the
    old `rotate` tag. The matrix is a fixed-size field, so no offset in the file moves. The
    video track is found by its handler type, never by position.
    """
    if degrees not in ROTATION_MATRICES:
        raise ValueError(f"rotation is one of {sorted(ROTATION_MATRICES)}, not {degrees}")
    out = bytearray(data)
    moov = [box for box in _boxes(out, 0, len(out)) if box[0] == b"moov"]
    if len(moov) != 1:
        raise ValueError(f"expected one moov box, found {len(moov)}")
    for name, start, end in _boxes(out, moov[0][1], moov[0][2]):
        if name != b"trak":
            continue
        children = {n: (s, e) for n, s, e in _boxes(out, start, end)}
        mdia = children.get(b"mdia")
        hdlr = {n: (s, e) for n, s, e in _boxes(out, *mdia)}.get(b"hdlr") if mdia else None
        # hdlr's payload: version and flags, a pre-defined word, then the handler type.
        if hdlr is None or out[hdlr[0] + 8 : hdlr[0] + 12] != b"vide":
            continue
        tkhd = children[b"tkhd"][0]
        at = tkhd + TKHD_MATRIX_OFFSET[out[tkhd]]
        out[at : at + 36] = struct.pack(">9i", *ROTATION_MATRICES[degrees])
        return bytes(out)
    raise ValueError("the file has no video track to rotate")


#: The subtitle cues `mkv_tracks` embeds: (start, end, text), plain SRT.
SUBTITLE_CUES = (
    (0.5, 2.0, "Lorem ipsum dolor sit amet."),
    (2.5, 4.5, "Consectetur adipiscing elit."),
)


def _srt(cues: tuple[tuple[float, float, str], ...]) -> str:
    def stamp(seconds: float) -> str:
        whole, millis = divmod(round(seconds * 1000), 1000)
        return f"00:00:{whole:02d},{millis:03d}"

    blocks = [f"{n}\n{stamp(a)} --> {stamp(b)}\n{text}\n" for n, (a, b, text) in enumerate(cues, 1)]
    return "\n".join(blocks)


def _chapters(count: int, duration: float) -> str:
    """An ffmetadata file splitting `duration` into `count` equal chapters."""
    step = round(duration * 1000) // count
    lines = [";FFMETADATA1"]
    for index in range(count):
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={index * step}",
            f"END={(index + 1) * step}",
            f"title=Chapter {index + 1}",
        ]
    return "\n".join(lines) + "\n"


@generator(parallel_safe=False)
def mkv_tracks(
    ctx: GeneratorContext,
    *,
    width: int,
    height: int,
    duration: float,
    fps: int = 30,
    tones: tuple[int, ...] = (440,),
    subtitles: bool = False,
    chapters: int = 0,
) -> bytes:
    """H.264 in Matroska with one AAC track per tone, and optionally SRT and chapters.

    What sets each mkv fixture apart lives in the container, not the codec: a second
    audio track, an embedded subtitle track, or a chapter list (docs/05 §3.3).
    """
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    workdir = ctx.workdir
    args = ["-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}"]
    maps = ["-map", "0:v"]
    for index, hz in enumerate(tones, 1):
        args += ["-f", "lavfi", "-i", f"sine=frequency={hz}:sample_rate=48000"]
        maps += ["-map", f"{index}:a"]
    extra = [
        "-c:v",
        encoder_for("h264"),
        *X264_ARGS,
        "-c:a",
        encoder_for("aac"),
        "-b:a",
        AUDIO_BITRATE,
    ]
    if subtitles:
        srt = workdir / "subtitles.srt"
        srt.write_text(_srt(SUBTITLE_CUES), encoding="utf-8")
        maps += ["-map", f"{len(tones) + 1}:s"]
        args += ["-i", str(srt)]
        extra += ["-c:s", "srt"]
    if chapters:
        meta = workdir / "chapters.txt"
        meta.write_text(_chapters(chapters, duration), encoding="utf-8")
        args += ["-i", str(meta)]
        extra += ["-map_chapters", str(len(tones) + 1 + int(subtitles))]
    args += ["-t", f"{duration:g}", *maps, *extra, "-f", "matroska"]
    return _encode(ctx, ".mkv", args)


#: Appended to the test pattern for `alpha`: a horizontal ramp, fully transparent at the left
#: edge and opaque at the right, so a player that drops the alpha plane shows the picture
#: whole and one that keeps it shows it fading in. The expression ignores time, so every
#: frame carries the same alpha.
ALPHA_RAMP = ",format=yuva420p,geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='255*X/(W-1)'"


@generator(parallel_safe=False)
def webm(
    ctx: GeneratorContext,
    *,
    width: int,
    height: int,
    duration: float,
    fps: int = 30,
    bitrate: str = "1M",
    container: str = "webm",
    vcodec: str = "vp9",
    alpha: bool = False,
) -> bytes:
    """VP9 video with Opus audio, or (`vcodec: vp8`) VP8 with Vorbis, in WebM or (`container:
    matroska`) general Matroska. `alpha` adds an alpha plane to the VP9 stream.

    `-row-mt 0` keeps the VP9 encode single-threaded, and libvpx cannot write alpha with
    alt-ref frames, so `alpha` turns them off (`-auto-alt-ref 0`).
    """
    if vcodec not in {"vp8", "vp9"}:
        raise ValueError(f"vcodec is vp8 or vp9, not {vcodec!r}")
    if alpha and vcodec != "vp9":
        raise ValueError("alpha is catalogued for VP9 only")
    args = _inputs(width, height, fps, duration, audio=True, effects=ALPHA_RAMP if alpha else "")
    if vcodec == "vp8":
        args += [
            "-c:v",
            encoder_for("vp8"),
            "-b:v",
            bitrate,
            "-threads",
            "1",
            "-deadline",
            "good",
            "-cpu-used",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            encoder_for("vorbis"),
            "-q:a",
            "4",
        ]
    else:
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
            "yuva420p" if alpha else "yuv420p",
            *(["-auto-alt-ref", "0"] if alpha else []),
            "-c:a",
            encoder_for("opus"),
            "-b:a",
            "96k",
        ]
    args += ["-f", container]
    return _encode(ctx, {"webm": ".webm", "matroska": ".mkv"}[container], args)


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
