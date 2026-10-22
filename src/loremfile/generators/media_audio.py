"""Audio fixtures: mp3, wav, flac, ogg, opus, m4a, aac, aiff (docs/05 §3.4).

Every waveform comes from ffmpeg's `lavfi` sources so that no sample data is copied from
anywhere: a 440 Hz sine, a stereo pair at 440/880 Hz, and digital silence. The bit-exact
flags live in `util.ffmpeg`; the M3.6 spike confirmed every encoder used here reproduces
byte for byte across processes *and* across invocations minutes apart, which is the check
that caught openpyxl in M3.5.

`with-id3v2-tags-3s.mp3` is the one fixture whose bytes are not written by ffmpeg alone:
mutagen adds the ID3v2 frames afterwards. docs/06 §4 claimed the tags carry no timestamp;
that is now verified rather than assumed, and the cover art is a published PNG fixture
read through `ctx.dependency` rather than a regenerated lookalike.
"""

from __future__ import annotations

import base64
import struct
from pathlib import Path

from mutagen.flac import Picture
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1
from mutagen.oggvorbis import OggVorbis

from loremfile.config import APPROX_TOLERANCE
from loremfile.generators.base import GeneratorContext, generator
from loremfile.util.ffmpeg import encoder_for, run
from loremfile.util.sizing import SizingError, fit

#: The waveforms docs/05 §3.4 names. Each maps to a lavfi source and, where the channels
#: are built separately, the filter that merges them.
FREQUENCY_HZ = 440
RIGHT_FREQUENCY_HZ = 880

#: ffmpeg's PCM encoder for each bit depth. 8-bit WAV is unsigned; everything wider is
#: signed little-endian, except AIFF, which is big-endian by definition.
PCM_ENCODERS = {8: "pcm_u8", 16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_f32le"}

#: A canonical WAV header: 12 bytes of RIFF, an 8+16 `fmt ` chunk, an 8-byte `data`
#: header. ffmpeg writes exactly this under `+bitexact`, which is what makes the sized
#: WAV fixtures exactly the size they claim.
WAV_HEADER_BYTES = 44
#: WAVE_FORMAT_EXTENSIBLE's IEEE-float sub-format, which ffmpeg writes for 32-bit float.
IEEE_FLOAT_GUID = bytes.fromhex("0300000000001000800000aa00389b71")
WAVE_FORMAT_EXTENSIBLE = 0xFFFE
WAVE_FORMAT_IEEE_FLOAT = 3

#: Bytes ffmpeg adds around an MP3 frame stream: the Xing/LAME header frame.
MP3_BITRATE = 128_000


def _target(ctx: GeneratorContext) -> Path:
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    return ctx.workdir / ctx.path.replace("/", "_")


def _source_args(source: str, sample_rate: int, channels: int) -> tuple[list[str], list[str]]:
    """(input arguments, mapping arguments) for one of the named waveforms."""
    if source == "sine":
        return (
            ["-f", "lavfi", "-i", f"sine=frequency={FREQUENCY_HZ}:sample_rate={sample_rate}"],
            [] if channels == 1 else ["-ac", str(channels)],
        )
    if source == "stereo-lr":
        # Two independent tones merged into one stereo stream: left 440 Hz, right 880 Hz.
        # This is the fixture people use to check that channels are not swapped.
        return (
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={FREQUENCY_HZ}:sample_rate={sample_rate}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={RIGHT_FREQUENCY_HZ}:sample_rate={sample_rate}",
                "-filter_complex",
                "[0:a][1:a]amerge=inputs=2[a]",
            ],
            ["-map", "[a]"],
        )
    if source == "silence":
        layout = "mono" if channels == 1 else "stereo"
        return (["-f", "lavfi", "-i", f"anullsrc=r={sample_rate}:cl={layout}"], [])
    known = "sine, stereo-lr, silence"
    raise ValueError(f"unknown audio source '{source}'; known: {known}")


def _encode(
    target: Path,
    *,
    source: str,
    duration: float,
    codec_args: list[str],
    sample_rate: int,
    channels: int,
    container: str | None = None,
) -> bytes:
    inputs, mapping = _source_args(source, sample_rate, channels)
    args = [*inputs, "-t", f"{duration:g}", *mapping, *codec_args]
    if container:
        args += ["-f", container]
    run([*args, str(target)])
    return target.read_bytes()


@generator()
def encoded(
    ctx: GeneratorContext,
    *,
    codec: str,
    duration: float,
    source: str = "sine",
    sample_rate: int = 48000,
    channels: int = 2,
    bitrate: str | None = None,
    quality: str | None = None,
    container: str | None = None,
    constant: bool = False,
) -> bytes:
    """One compressed audio fixture: mp3, flac, vorbis, opus or AAC."""
    codec_args = ["-c:a", encoder_for(codec)]
    if bitrate:
        codec_args += ["-b:a", bitrate]
    if quality:
        codec_args += ["-q:a", quality]
    if constant:
        # libopus is variable-rate by default and overshoots on a pure tone, so the rate
        # asked for is not the rate measured. Constant rate makes them the same.
        codec_args += ["-vbr", "off"]
    if codec == "mp3":
        # Without a Xing header, players cannot seek a CBR MP3 accurately and every
        # duration readout is an estimate from the file size.
        codec_args += ["-write_xing", "1"]
    return _encode(
        _target(ctx),
        source=source,
        duration=duration,
        codec_args=codec_args,
        sample_rate=sample_rate,
        channels=channels,
        container=container,
    )


@generator()
def pcm(
    ctx: GeneratorContext,
    *,
    duration: float,
    source: str = "sine",
    sample_rate: int = 44100,
    bits: int = 16,
    channels: int = 2,
    container: str = "wav",
    info: dict[str, str] | None = None,
) -> bytes:
    """Uncompressed PCM: WAV or AIFF.

    `info` becomes a RIFF LIST/INFO chunk (INAM, IART, ...) written before `data`, the
    metadata real recorders add and the reason samples need not start at byte 44.
    """
    if bits not in PCM_ENCODERS:
        raise ValueError(f"no PCM encoder for {bits}-bit; known: {sorted(PCM_ENCODERS)}")
    encoder = "pcm_s16be" if container == "aiff" else PCM_ENCODERS[bits]
    tags = [
        arg
        for key, value in sorted((info or {}).items())
        for arg in ("-metadata", f"{key}={value}")
    ]
    return _encode(
        _target(ctx),
        source=source,
        duration=duration,
        codec_args=["-c:a", encoder, "-ar", str(sample_rate), "-ac", str(channels), *tags],
        sample_rate=sample_rate,
        channels=channels,
        container=container,
    )


@generator(parallel_safe=False)
def wav_sized(
    ctx: GeneratorContext,
    *,
    size: int,
    sample_rate: int = 44100,
    bits: int = 16,
    channels: int = 2,
) -> bytes:
    """A WAV of *exactly* ``size`` bytes (docs/05 §6 — an exact class, not approx).

    The arithmetic is the whole point: a 44-byte canonical header plus ``frames x block``
    bytes of PCM. ffmpeg is asked for slightly more audio than needed and the result is
    trimmed to the frame, because `-t` takes seconds and the exact frame count is not
    generally reachable through a float. Trimming raw PCM is lossless; the two length
    fields in the header are then rewritten to match.
    """
    block = channels * bits // 8
    payload = size - WAV_HEADER_BYTES
    if payload <= 0 or payload % block:
        raise SizingError(
            f"{ctx.path}: {size} bytes cannot be an exact WAV at {bits}-bit x{channels}: "
            f"{payload} bytes of audio is not a whole number of {block}-byte frames"
        )
    frames = payload // block
    generous = (frames / sample_rate) + 1
    data = pcm(
        ctx,
        duration=generous,
        sample_rate=sample_rate,
        bits=bits,
        channels=channels,
        container="wav",
    )
    if len(data) < size:
        raise SizingError(f"{ctx.path}: ffmpeg produced {len(data)} bytes, needed {size}")

    trimmed = bytearray(data[:size])
    # RIFF size covers everything after the first 8 bytes; data size is the audio alone.
    struct.pack_into("<I", trimmed, 4, size - 8)
    struct.pack_into("<I", trimmed, 40, payload)
    return bytes(trimmed)


def ieee_float_header(data: bytes) -> bytes:
    """ffmpeg's extensible 32-bit float WAV with the plain IEEE-float header instead.

    The samples are kept byte for byte. The header becomes an 18-byte `fmt ` with format
    tag 3 and no extension, then the `fact` chunk (frame count) that every WAV whose format
    is not integer PCM must carry, then `data`.
    """
    chunks: dict[bytes, bytes] = {}
    offset = 12
    while offset + 8 <= len(data):
        (size,) = struct.unpack("<I", data[offset + 4 : offset + 8])
        chunks[data[offset : offset + 4]] = data[offset + 8 : offset + 8 + size]
        if data[offset : offset + 4] == b"data":
            break
        offset += 8 + size + (size & 1)
    fmt, samples = chunks.get(b"fmt ", b""), chunks.get(b"data")
    tag, channels, rate, per_second, align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if (tag, bits, fmt[24:40]) != (WAVE_FORMAT_EXTENSIBLE, 32, IEEE_FLOAT_GUID) or not samples:
        raise ValueError(f"not an extensible 32-bit float WAV: tag 0x{tag:04x}, {bits}-bit")
    frames = len(samples) // align
    body = (
        b"WAVE"
        + b"fmt "
        + struct.pack(
            "<IHHIIHHH", 18, WAVE_FORMAT_IEEE_FLOAT, channels, rate, per_second, align, bits, 0
        )
        + b"fact"
        + struct.pack("<II", 4, frames)
        + b"data"
        + struct.pack("<I", len(samples))
        + samples
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


@generator(parallel_safe=False)
def wav_float(
    ctx: GeneratorContext, *, duration: float, sample_rate: int = 44100, channels: int = 2
) -> bytes:
    """32-bit float samples behind format tag 3, WAVE_FORMAT_IEEE_FLOAT (docs/05 §3.4).

    ffmpeg writes float as WAVE_FORMAT_EXTENSIBLE, a header the 24-bit fixture already
    covers, so its samples are kept and its header rewritten (`ieee_float_header`).
    """
    extensible = pcm(ctx, duration=duration, sample_rate=sample_rate, bits=32, channels=channels)
    return ieee_float_header(extensible)


@generator(parallel_safe=False)
def mp3_sized(ctx: GeneratorContext, *, size: int) -> bytes:
    """An MP3 of about ``size`` bytes at a constant 128 kbps (docs/05 §6).

    Duration is the free variable: bytes = bitrate x seconds / 8, less a little for the
    Xing frame, so the first guess is analytic and `fit` only has to correct rounding.
    """

    def make(milliseconds: int) -> bytes:
        return encoded(
            ctx, codec="mp3", duration=milliseconds / 1000, bitrate=f"{MP3_BITRATE // 1000}k"
        )

    start = round(size * 8 / MP3_BITRATE * 0.995 * 1000)
    _, payload = fit(size, APPROX_TOLERANCE, make, n0=start, n_min=100, n_max=3_600_000)
    return payload


@generator()
def mp3_tagged(
    ctx: GeneratorContext,
    *,
    duration: float,
    cover: str,
    title: str = "Loremfile Test Tone",
    artist: str = "loremfile.dev",
    album: str = "loremfile.dev samples",
    year: str = "2020",
    genre: str = "Test Tone",
) -> bytes:
    """An MP3 carrying ID3v2.3 tags and cover art, written by mutagen.

    Every value is fixed and none is a timestamp: `TDRC` is the literal year from the
    catalog, not the build date. mutagen writes no modification time of its own, which
    the run-twice test in `tests/unit/test_determinism.py` is there to keep true.
    """
    target = _target(ctx)
    encoded_bytes = encoded(ctx, codec="mp3", duration=duration, bitrate=f"{MP3_BITRATE // 1000}k")
    target.write_bytes(encoded_bytes)

    tags = ID3()
    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=artist))
    tags.add(TALB(encoding=3, text=album))
    tags.add(TDRC(encoding=3, text=year))
    tags.add(TCON(encoding=3, text=genre))
    tags.add(
        APIC(
            encoding=3,
            mime="image/png",
            type=3,  # front cover
            desc="Cover",
            data=ctx.dependency(cover),
        )
    )
    # v2_version=3 because ID3v2.3 is what every player reads; 2.4 is still patchy.
    tags.save(target, v2_version=3)
    return target.read_bytes()


@generator()
def vorbis_tagged(
    ctx: GeneratorContext,
    *,
    duration: float,
    tags: dict[str, str],
    cover: str,
    quality: str = "4",
) -> bytes:
    """Vorbis carrying comments and a front cover in METADATA_BLOCK_PICTURE.

    The cover is a published JPEG read through `ctx.dependency`, as the MP3 cover is. Its
    base64 form makes the comment header longer than one Ogg page, which is the property a
    parser that reads one header page and starts decoding gets wrong. mutagen rewrites only
    the header pages; their bytes depend on nothing but the input (spiked twice, 2026-10-16).
    """
    target = _target(ctx)
    _encode(
        target,
        source="sine",
        duration=duration,
        codec_args=["-c:a", encoder_for("vorbis"), "-q:a", quality],
        sample_rate=48000,
        channels=2,
        container="ogg",
    )
    vorbis = OggVorbis(target)
    # ffmpeg writes ENCODER=Lavc libvorbis even under +bitexact; the comments here are
    # exactly the ones the catalog names, so the measured set is the authored set.
    for key in list(vorbis.keys()):
        del vorbis[key]
    for key, value in tags.items():
        vorbis[key] = [value]
    picture = Picture()
    picture.type = 3  # front cover
    picture.mime = "image/jpeg"
    picture.desc = "Cover"
    picture.data = ctx.dependency(cover)
    vorbis["METADATA_BLOCK_PICTURE"] = [base64.b64encode(picture.write()).decode("ascii")]
    vorbis.save()
    return target.read_bytes()


@generator()
def chained(
    ctx: GeneratorContext,
    *,
    codec: str,
    segment: float,
    frequencies: list[int],
    quality: str = "4",
) -> bytes:
    """Chained Ogg: one logical bitstream per frequency, back to back (RFC 3533 §4).

    Chaining is concatenation, valid only when each stream has its own serial number, so
    each segment is muxed with a different `serial_offset`. ffprobe reports the first chain
    alone, which is the reader behaviour this fixture exists to expose.
    """
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    parts = []
    for index, frequency in enumerate(frequencies, start=1):
        target = ctx.workdir / f"chain-{index}.ogg"
        run(
            [
                "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000",
                "-t", f"{segment:g}", "-ac", "2",
                "-c:a", encoder_for(codec), "-q:a", quality,
                "-serial_offset", str(index), "-f", "ogg", str(target),
            ]
        )  # fmt: skip
        parts.append(target.read_bytes())
    return b"".join(parts)
