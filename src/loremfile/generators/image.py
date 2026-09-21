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
import subprocess
import tempfile
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


def _convert(image: Image.Image, mode: str, width: int, height: int) -> Image.Image:
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
        return Image.linear_gradient("L").resize((width, height)).convert("I;16")
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
    """A JPEG whose pixels are stored rotated, with the EXIF tag that corrects it.

    The label reads the right way up **only** when the viewer honours the tag, which is
    the whole point: a viewer that ignores EXIF shows it sideways.
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
def ico_multi(_ctx: GeneratorContext, *, sizes: list[int]) -> bytes:
    """A multi-resolution ICO, the shape a real favicon has."""
    largest = max(sizes)
    image = test_card(largest, largest, "RGBA")
    buffer = io.BytesIO()
    image.save(buffer, format="ICO", sizes=[(s, s) for s in sorted(sizes)])
    return buffer.getvalue()


@generator(parallel_safe=False)
def avif_from_png(ctx: GeneratorContext, *, width: int, height: int, quality: int = 60) -> bytes:
    """AVIF, encoded by `avifenc` from a PNG test card.

    `--jobs 1 --speed 6` per docs/06 §4: multi-threaded AV1 encoding makes
    timing-dependent choices and would not reproduce byte for byte.
    """
    png = testcard(ctx, width=width, height=height, fmt="PNG")
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
