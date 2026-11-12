"""Raster image fixtures (docs/05 §3.2).

Every image is a test card: colour bars, a centre cross, a one-pixel border and a label
giving the dimensions and mode. That makes a fixture self-describing — if you open it and
the label says 640x480 RGB, you know what you have — and it makes orientation and
colour-space bugs visible rather than subtle.

Pillow writes no timestamps by default, but a few plugins do, so nothing here relies on
that: text is drawn with the pinned default font, and every save passes explicit options.
"""

from __future__ import annotations

import io
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from loremfile.config import APPROX_TOLERANCE
from loremfile.generators.base import GeneratorContext, generator
from loremfile.util.ffmpeg import FfmpegError
from loremfile.util.sizing import fit

#: SMPTE-ish bars. Fixed, so the same colours appear in every format.
BARS = (
    (255, 255, 255),
    (255, 255, 0),
    (0, 255, 255),
    (0, 255, 0),
    (255, 0, 255),
    (255, 0, 0),
    (0, 0, 255),
    (0, 0, 0),
)

#: Pillow's bundled bitmap font. `load_default(size)` is deterministic for a pinned
#: Pillow, which is why the toolchain digest matters for images as much as for video.
LABEL_SIZE = 16

#: Below these sizes the decorations would swamp the image, so they are skipped.
MIN_DECORATED = 8
MIN_LABEL_WIDTH = 64
MIN_LABEL_HEIGHT = 24

#: Pillow treats WebP quality 100 as the lossless switch.
WEBP_LOSSLESS_QUALITY = 100


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size)
    except (AttributeError, TypeError):  # very old Pillow
        return ImageFont.load_default()


def test_card(width: int, height: int, mode: str = "RGB", label: str | None = None) -> Image.Image:
    """A colour-bar test card with a border, a centre cross and a label."""
    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Boundaries are computed proportionally rather than by a fixed bar width, so an
    # image narrower than the number of bars still works: bars that would be empty are
    # skipped instead of producing a rectangle whose right edge is left of its left one.
    for index, colour in enumerate(BARS):
        left = index * width // len(BARS)
        right = (index + 1) * width // len(BARS)
        if right <= left:
            continue
        draw.rectangle([left, 0, right - 1, height - 1], fill=colour)

    if width >= MIN_DECORATED and height >= MIN_DECORATED:
        draw.rectangle([0, 0, width - 1, height - 1], outline=(128, 128, 128))
        draw.line([0, height // 2, width - 1, height // 2], fill=(128, 128, 128))
        draw.line([width // 2, 0, width // 2, height - 1], fill=(128, 128, 128))

    text = label if label is not None else f"{width}x{height} {mode}"
    if width >= MIN_LABEL_WIDTH and height >= MIN_LABEL_HEIGHT:
        draw.rectangle([4, 4, min(width - 5, 4 + 9 * len(text)), 22], fill=(0, 0, 0))
        draw.text((6, 6), text, fill=(255, 255, 255), font=_font(LABEL_SIZE))

    return _convert(image, mode, width, height)


def _convert(image: Image.Image, mode: str, width: int, height: int) -> Image.Image:  # noqa: PLR0911 - one return per mode
    """Move the RGB card into the requested mode, adding alpha or palette as needed."""
    if mode == "RGB":
        return image
    if mode == "RGBA":
        out = image.convert("RGBA")
        # A horizontal alpha ramp, so transparency is visible rather than uniform.
        alpha = Image.linear_gradient("L").resize((width, height)).rotate(270)
        out.putalpha(alpha)
        return out
    if mode == "L":
        return image.convert("L")
    if mode == "P":
        return image.convert("P", palette=Image.Palette.ADAPTIVE, colors=64)
    if mode == "CMYK":
        return image.convert("CMYK")
    if mode == "I;16":
        # A diagonal ramp over the whole 16-bit range. The ramp this branch wrote before was
        # an 8-bit gradient in a 16-bit container, every sample below 256, so a decoder that
        # kept only the low 8 bits showed the same picture. Along one axis a 256-wide image
        # would step by exactly 257, low byte equal to high; on a diagonal it does not. No
        # published fixture takes this branch.
        span = max(width + height - 2, 1)
        ramp = Image.new("I", (width, height))
        ramp.putdata([(x + y) * 65535 // span for y in range(height) for x in range(width)])
        return ramp.convert("I;16")
    if mode == "I;16B":
        # The card itself at 16 bits, big-endian: the only mode Pillow writes in Motorola
        # byte order ("MM"), so a TIFF reader assuming Intel order or 8-bit samples fails.
        return image.convert("L").convert("I").point(lambda value: value * 257).convert("I;16B")
    raise ValueError(f"unsupported mode {mode!r}")


def _noise(ctx: GeneratorContext, width: int, height: int) -> Image.Image:
    """Seeded RGB noise: incompressible, which is what a size-named image needs."""
    payload = ctx.stream(width * height * 3)
    return Image.frombytes("RGB", (width, height), payload)


def _save(image: Image.Image, fmt: str, **options: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


@generator()
def multipage_tiff(_ctx: GeneratorContext, *, width: int, height: int, pages: int) -> bytes:
    """A TIFF of `pages` test cards, each labelled with its page number, so a reader that
    shows only the first page is visibly wrong rather than plausibly right."""
    cards = [test_card(width, height, label=f"page {n} of {pages}") for n in range(1, pages + 1)]
    return _save(cards[0], "TIFF", save_all=True, append_images=cards[1:], compression="raw")


@generator()
def testcard(
    _ctx: GeneratorContext,
    *,
    width: int,
    height: int,
    fmt: str,
    mode: str = "RGB",
    quality: int = 85,
    progressive: bool = False,
    interlaced: bool = False,
    optimize: bool = False,
    compression: str | None = None,
) -> bytes:
    """One test card saved in the requested format."""
    if interlaced:
        # Pillow's PNG writer hard-codes the interlace flag to 0 and ignores the option, so
        # `interlaced=True` used to produce a plain file under an interlaced name.
        raise ValueError("Pillow cannot write an interlaced PNG; use image.png_interlaced")
    image = test_card(width, height, mode)
    if fmt == "PNG":
        return _save(image, "PNG", optimize=optimize, interlace=1 if interlaced else 0)
    if fmt == "JPEG":
        return _save(image, "JPEG", quality=quality, progressive=progressive, subsampling="4:2:0")
    if fmt == "GIF":
        return _save(image.convert("P", palette=Image.Palette.ADAPTIVE, colors=256), "GIF")
    if fmt == "WEBP":
        return _save(image, "WEBP", quality=quality, lossless=quality >= WEBP_LOSSLESS_QUALITY)
    if fmt == "BMP":
        return _save(image, "BMP")
    if fmt == "TIFF":
        return _save(image, "TIFF", compression=compression or "raw")
    raise ValueError(f"unsupported format {fmt!r}")


#: The Adam7 passes, as (first column, first row, column step, row step).
ADAM7_PASSES = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)
PNG_SIGNATURE_BYTES = b"\x89PNG\r\n\x1a\n"


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload))
    )


@generator()
def png_interlaced(_ctx: GeneratorContext, *, width: int, height: int) -> bytes:
    """The RGB test card as an Adam7 interlaced PNG, with the seven passes written here.

    Pillow reads interlaced PNGs but its writer always sets the flag to 0. Each pass holds
    every `step`-th pixel of every `step`-th row from its own offset, each row led by a filter
    byte (0, none); a pass with no pixels is left out, which small images need.
    """
    rgb = test_card(width, height, "RGB").tobytes()
    raw = bytearray()
    for first_column, first_row, column_step, row_step in ADAM7_PASSES:
        columns = range(first_column, width, column_step)
        if not columns:
            continue
        for y in range(first_row, height, row_step):
            raw.append(0)
            for x in columns:
                offset = (y * width + x) * 3
                raw += rgb[offset : offset + 3]
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 1)
    return (
        PNG_SIGNATURE_BYTES
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _png_chunk(b"IEND", b"")
    )


@generator()
def animated(
    _ctx: GeneratorContext,
    *,
    width: int,
    height: int,
    frames: int,
    fmt: str,
    duration_ms: int = 100,
) -> bytes:
    """An animation whose frames differ visibly: the bars shift one step per frame."""
    sequence = []
    for index in range(frames):
        rotated = BARS[index % len(BARS) :] + BARS[: index % len(BARS)]
        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        for position, colour in enumerate(rotated):
            left = position * width // len(rotated)
            right = (position + 1) * width // len(rotated)
            if right <= left:
                continue
            draw.rectangle([left, 0, right - 1, height - 1], fill=colour)
        draw.text((4, 4), f"{index + 1}/{frames}", fill=(0, 0, 0), font=_font(LABEL_SIZE))
        sequence.append(image)

    buffer = io.BytesIO()
    if fmt == "PNG":  # APNG
        sequence[0].save(
            buffer,
            format="PNG",
            save_all=True,
            append_images=sequence[1:],
            duration=duration_ms,
            loop=0,
        )
    elif fmt == "GIF":
        palette = [
            frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=256) for frame in sequence
        ]
        palette[0].save(
            buffer,
            format="GIF",
            save_all=True,
            append_images=palette[1:],
            duration=duration_ms,
            loop=0,
        )
    elif fmt == "WEBP":
        sequence[0].save(
            buffer,
            format="WEBP",
            save_all=True,
            append_images=sequence[1:],
            duration=duration_ms,
            loop=0,
            lossless=True,
        )
    else:
        raise ValueError(f"{fmt!r} does not support animation here")
    return buffer.getvalue()


#: Sized noise images are a fixed width with a variable height, so bytes scale
#: *linearly* with the fitted parameter. docs/05 §6 originally said "n = side length of
#: a square image"; that makes size grow with n², which `fit`'s proportional secant step
#: systematically overshoots — the 10 MB JPEG exhausted all twelve attempts and failed
#: the build. Varying one dimension keeps the relationship linear and converges in two
#: or three steps.
NOISE_WIDTH = 1024


@generator(parallel_safe=False)
def noise_sized(ctx: GeneratorContext, *, size: int, fmt: str, quality: int = 95) -> bytes:
    """Seeded noise fitted to within 5 % of ``size``.

    Noise does not compress, so the byte count tracks the pixel count closely.
    """

    def make(height: int) -> bytes:
        image = _noise(ctx, NOISE_WIDTH, height)
        if fmt == "PNG":
            return _save(image, "PNG", compress_level=6)
        return _save(image, "JPEG", quality=quality, subsampling="4:4:4")

    # Roughly three bytes per pixel for PNG noise, a little less for JPEG at q95.
    start = max(size // (3 * NOISE_WIDTH), 8)
    _, payload = fit(size, APPROX_TOLERANCE, make, n0=start, n_min=8, n_max=200_000)
    return payload


@generator()
def exif_orientation(_ctx: GeneratorContext, *, width: int, height: int, orientation: int) -> bytes:
    """Preserve the published orientation-6 recipe, including its inverted display.

    Its stored pixels and tag both rotate clockwise. Use exif_rotated for an upright
    displayed card; changing this recipe would change bytes at an immutable path.
    """
    image = test_card(width, height, "RGB", label=f"UP orientation={orientation}")
    rotations = {1: 0, 3: 180, 6: 270, 8: 90}
    if orientation not in rotations:
        raise ValueError(f"unsupported EXIF orientation {orientation}")
    stored = image.rotate(rotations[orientation], expand=True)

    exif = Image.Exif()
    exif[0x0112] = orientation  # Orientation
    exif[0x010E] = "loremfile.dev EXIF orientation fixture"  # ImageDescription
    exif[0x0132] = "2020:01:01 00:00:00"  # DateTime, fixed
    return _save(stored, "JPEG", quality=90, exif=exif.tobytes(), subsampling="4:2:0")


@generator()
def exif_rotated(_ctx: GeneratorContext, *, width: int, height: int) -> bytes:
    """Orientation 8: pixels rotated clockwise, displayed counterclockwise by EXIF."""
    image = test_card(width, height, "RGB", label="UP orientation=8")
    stored = image.transpose(Image.Transpose.ROTATE_270)
    exif = Image.Exif()
    exif[0x0112] = 8
    exif[0x010E] = "loremfile.dev EXIF orientation fixture"
    exif[0x0132] = "2020:01:01 00:00:00"
    return _save(stored, "JPEG", quality=90, exif=exif.tobytes(), subsampling="4:2:0")


#: EXIF's GPS and Exif sub-IFD pointers, and the tags written into them.
GPS_IFD, EXIF_IFD = 0x8825, 0x8769


@generator()
def exif_gps(_ctx: GeneratorContext, *, width: int, height: int) -> bytes:
    """A test card with a GPS position and a capture time: 0 N 0 E (Null Island) at 2020-01-01.

    The position is a place nobody lives, so the file carries no real location; it is what a
    pipeline that strips or reads EXIF location has to find.
    """
    image = test_card(width, height, "RGB", label="EXIF GPS 0N 0E")
    exif = Image.Exif()
    exif[0x010E] = "loremfile.dev EXIF GPS fixture"  # ImageDescription
    exif[0x0132] = "2020:01:01 00:00:00"  # DateTime
    exif.get_ifd(EXIF_IFD)[0x9003] = "2020:01:01 00:00:00"  # DateTimeOriginal
    gps = exif.get_ifd(GPS_IFD)
    gps[0x0001], gps[0x0002] = "N", (0.0, 0.0, 0.0)  # GPSLatitudeRef, GPSLatitude
    gps[0x0003], gps[0x0004] = "E", (0.0, 0.0, 0.0)  # GPSLongitudeRef, GPSLongitude
    return _save(image, "JPEG", quality=85, exif=exif.tobytes(), subsampling="4:2:0")


@generator()
def gif_transparent(_ctx: GeneratorContext, *, width: int, height: int) -> bytes:
    """A test card whose right half is transparent. GIF transparency is on or off: one palette
    index is declared transparent, so the PNG fixture's alpha ramp becomes a hard edge."""
    card = test_card(width, height, "RGB")
    # One colour fewer, so index 255 is free to be the transparent one.
    indexed = card.convert("P", palette=Image.Palette.ADAPTIVE, colors=255)
    indexed.paste(255, (width // 2, 0, width, height))
    return _save(indexed, "GIF", transparency=255)


@generator()
def ico_multi(_ctx: GeneratorContext, *, sizes: list[int]) -> bytes:
    """A multi-resolution ICO, the shape a real favicon has."""
    largest = max(sizes)
    image = test_card(largest, largest, "RGBA")
    buffer = io.BytesIO()
    image.save(buffer, format="ICO", sizes=[(s, s) for s in sorted(sizes)])
    return buffer.getvalue()


@generator(parallel_safe=False)
def avif_from_png(
    ctx: GeneratorContext, *, width: int, height: int, quality: int = 60, alpha: bool = False
) -> bytes:
    """AVIF, encoded by `avifenc` from a PNG test card, an RGBA one with an alpha ramp if `alpha`.

    `--jobs 1 --speed 6` per docs/06 §4: multi-threaded AV1 encoding makes
    timing-dependent choices and would not reproduce byte for byte.
    """
    png = testcard(ctx, width=width, height=height, fmt="PNG", mode="RGBA" if alpha else "RGB")
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ctx.workdir) as temporary:
        source = Path(temporary) / "card.png"
        target = Path(temporary) / "card.avif"
        source.write_bytes(png)
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, paths we built
            [
                ctx.tool("avifenc"),
                "--jobs",
                "1",
                "--speed",
                "6",
                "--min",
                "0",
                "--max",
                str(max(0, 63 - quality * 63 // 100)),
                str(source),
                str(target),
            ],
            capture_output=True,
            timeout=300,
            check=False,
        )
        if completed.returncode != 0:
            tail = completed.stderr.decode("utf-8", "replace").strip()[-400:]
            raise FfmpegError(f"avifenc exited {completed.returncode}: {tail}")
        return target.read_bytes()


#: x265 parameters for heif-enc. One thread pool and one frame thread, as for every other
#: encoder here; `asm=0` because the spike gave identical bytes at every SIMD level from
#: AVX2 down to none, and turning the kernels off removes the one level it could not test.
X265_PARAMS = ("x265:pools=none", "x265:frame-threads=1", "x265:asm=0")


@generator(parallel_safe=False)
def heic_from_png(ctx: GeneratorContext, *, width: int, height: int, quality: int = 60) -> bytes:
    """HEIC, encoded by `heif-enc` (libheif with x265) from a PNG test card."""
    png = testcard(ctx, width=width, height=height, fmt="PNG")
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ctx.workdir) as temporary:
        source = Path(temporary) / "card.png"
        target = Path(temporary) / "card.heic"
        source.write_bytes(png)
        params = [arg for param in X265_PARAMS for arg in ("-p", param)]
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, paths we built
            [ctx.tool("heif-enc"), "-q", str(quality), *params, "-o", str(target), str(source)],
            capture_output=True,
            timeout=300,
            check=False,
        )
        if completed.returncode != 0:
            tail = completed.stderr.decode("utf-8", "replace").strip()[-400:]
            raise FfmpegError(f"heif-enc exited {completed.returncode}: {tail}")
        return target.read_bytes()
