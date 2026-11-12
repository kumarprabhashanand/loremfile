"""Catalogue 1.13.0: the phase-1 image rows that were not in the launch set.

Eighteen files in six formats. Every file is built twice in fresh directories and must match
itself and the committed manifest. Every control builds the file without its one declared
difference, or builds the nearest ordinary file instead, and watches the validator refuse it
for the property that difference carries. Every structural check the validators gained is
shown to fire on a file broken in exactly that way, and every claim a description makes is
pinned to the fact that makes it true.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageChops, ImageOps, ImageStat

from loremfile.build import load_generators
from loremfile.catalog import Catalog
from loremfile.generators import image as image_generators
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import load, validate
from loremfile.validators.image import _jpeg_quality, _webp_codecs

ROOT = Path(__file__).resolve().parents[2]
CATALOG = Catalog.load()
MANIFEST = {e["path"]: e for e in json.loads((ROOT / "manifest.json").read_text())["fixtures"]}
load_generators()
load()

PATHS = (
    "png/3840x2160.png",
    "png/indexed-8bit-256x256.png",
    "png/16bit-256x256.png",
    "png/interlaced-512x512.png",
    "png/10mb.png",
    "jpg/grayscale-640x480.jpg",
    "jpg/quality-10-640x480.jpg",
    "jpg/exif-orientation-1-640x480.jpg",
    "jpg/exif-orientation-3-640x480.jpg",
    "jpg/exif-gps-640x480.jpg",
    "gif/static-256x256.gif",
    "gif/transparent-256x256.gif",
    "webp/lossless-640x480.webp",
    "webp/animated-10frames-256x256.webp",
    "avif/alpha-256x256.avif",
    "svg/text-and-gradient.svg",
    "svg/viewbox-responsive.svg",
    "svg/icons-24x24.svg",
)


def build(path: str, directory: Path, generator: str | None = None, **overrides: Any) -> bytes:
    """The fixture as catalogued, or with `overrides`, or by another generator entirely."""
    directory.mkdir(parents=True, exist_ok=True)
    entry = CATALOG.by_path[path]
    context = GeneratorContext(path=path, workdir=directory)
    params = overrides if generator else entry.params | overrides
    with deterministic(context.seed):
        out = REGISTRY.get(generator or entry.generator)(context, **params)
    return out if isinstance(out, bytes) else out.read_bytes()


def failures(path: str, data: bytes) -> list[str]:
    entry = CATALOG.by_path[path]
    return validate(data, entry, CATALOG.mime_for(entry)).failures


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("catalog-1-13")
    return {path: build(path, root / str(index)) for index, path in enumerate(PATHS)}


def test_the_batch_is_eighteen_files_in_six_formats() -> None:
    """Named, so a catalog edit that drops a row fails here rather than shrinking the suite."""
    assert len(PATHS) == len(set(PATHS)) == 18
    assert all(path in CATALOG.by_path for path in PATHS)
    counts = {fmt: sum(p.startswith(f"{fmt}/") for p in PATHS) for fmt in ("png", "jpg", "svg")}
    assert counts == {"png": 5, "jpg": 5, "svg": 3}
    assert {path.split("/")[0] for path in PATHS} == {"png", "jpg", "gif", "webp", "avif", "svg"}
    assert "jpg/cmyk-640x640.jpg" not in PATHS, "phase 2, published in 1.8.0"
    assert not any(p.startswith("tiff/") for p in PATHS), "the four 1.9.0 tiffs are not these"


@pytest.mark.container
@pytest.mark.parametrize("path", PATHS)
def test_each_file_validates_and_reproduces_in_a_fresh_directory(path, built, tmp_path):
    entry = CATALOG.by_path[path]
    report = validate(built[path], entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures
    assert built[path] == build(path, tmp_path)
    # The committed manifest is the lock: what is built here is what it published.
    assert hashlib.sha256(built[path]).hexdigest() == MANIFEST[path]["sha256"]
    assert len(built[path]) == MANIFEST[path]["bytes"]
    assert report.props == MANIFEST[path]["props"]


# --- every file is refused without its difference -------------------------------------------

#: (path, substitute generator or None, parameters that remove the difference, what is refused).
WITHOUT: tuple[tuple[str, str | None, dict[str, Any], str], ...] = (
    ("png/3840x2160.png", None, {"width": 1920, "height": 1080}, "expect.width"),
    ("png/indexed-8bit-256x256.png", None, {"mode": "RGB"}, "expect.mode"),
    ("png/16bit-256x256.png", None, {"mode": "L"}, "expect.mode"),
    (
        "png/interlaced-512x512.png",
        "image.testcard",
        {"width": 512, "height": 512, "fmt": "PNG"},
        "expect.interlaced",
    ),
    ("png/10mb.png", None, {"size": 1_000_000}, "size_class"),
    ("jpg/grayscale-640x480.jpg", None, {"mode": "RGB"}, "expect.mode"),
    ("jpg/quality-10-640x480.jpg", None, {"quality": 85}, "quantization tables"),
    ("jpg/exif-orientation-1-640x480.jpg", None, {"orientation": 3}, "expect.exif_orientation"),
    ("jpg/exif-orientation-3-640x480.jpg", None, {"orientation": 1}, "expect.exif_orientation"),
    (
        "jpg/exif-gps-640x480.jpg",
        "image.testcard",
        {"width": 640, "height": 480, "fmt": "JPEG"},
        "expect.gps_latitude",
    ),
    ("gif/static-256x256.gif", None, {"width": 128, "height": 128}, "expect.width"),
    (
        "gif/transparent-256x256.gif",
        "image.testcard",
        {"width": 256, "height": 256, "fmt": "GIF"},
        "expect.transparent_pixels",
    ),
    ("webp/lossless-640x480.webp", None, {"quality": 80}, "which is lossless"),
    ("webp/animated-10frames-256x256.webp", None, {"frames": 2}, "expect.frames"),
    ("avif/alpha-256x256.avif", None, {"alpha": False}, "expect.mode"),
    ("svg/text-and-gradient.svg", "svg.simple_shapes", {}, "expect.gradients"),
    ("svg/viewbox-responsive.svg", "svg.simple_shapes", {}, "expect.width"),
    ("svg/icons-24x24.svg", "svg.simple_shapes", {}, "expect.symbols"),
)


def test_the_controls_cover_every_file() -> None:
    """Empty-set control: a path left out of the table above is a file nothing refuses."""
    assert {path for path, *_ in WITHOUT} == set(PATHS)


@pytest.mark.parametrize(
    ("path", "generator", "overrides", "refused_for"),
    WITHOUT,
    ids=[f"{path}-{refused_for}" for path, _, _, refused_for in WITHOUT],
)
def test_each_file_is_refused_without_its_difference(
    path, generator, overrides, refused_for, tmp_path
):
    found = failures(path, build(path, tmp_path, generator, **overrides))
    assert any(refused_for in failure for failure in found), (refused_for, found)


# --- the structural checks each fire on a file broken in exactly that way -------------------


def swapped(data: bytes, old: str, new: str) -> bytes:
    assert old.encode() in data, f"control: {old!r} is in the file"
    return data.replace(old.encode(), new.encode(), 1)


def refused_with(path: str, whole: bytes, broken: bytes, message: str) -> None:
    """`broken` is refused for `message`; the control is that `whole`, as built, is not."""
    assert failures(path, whole) == [], "control: it passes as built"
    found = failures(path, broken)
    assert any(message in failure for failure in found), (message, found)


def test_a_use_and_a_gradient_that_name_nothing_are_each_refused(built) -> None:
    sheet, gradient = "svg/icons-24x24.svg", "svg/text-and-gradient.svg"
    refused_with(
        sheet,
        built[sheet],
        swapped(built[sheet], 'href="#icon-circle"', 'href="#icon-missing"'),
        "which no element holds",
    )
    refused_with(
        gradient,
        built[gradient],
        swapped(built[gradient], "url(#sky)", "url(#nowhere)"),
        "reads url(#nowhere)",
    )


def test_a_gps_block_without_its_longitude_is_refused() -> None:
    path = "jpg/exif-gps-640x480.jpg"
    exif = Image.Exif()
    gps = exif.get_ifd(image_generators.GPS_IFD)
    gps[1], gps[2] = "N", (0.0, 0.0, 0.0)
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480)).save(buffer, "JPEG", quality=85, exif=exif.tobytes())
    assert any("lacks tag" in f for f in failures(path, buffer.getvalue()))


def test_the_gps_position_is_signed_by_its_reference() -> None:
    """South and west are negative. The catalogued file is 0 N 0 E, which cannot show it,
    so a file at 10 S 20 W is read the way a viewer reads it."""
    exif = Image.Exif()
    gps = exif.get_ifd(image_generators.GPS_IFD)
    gps[1], gps[2], gps[3], gps[4] = "S", (10.0, 0.0, 0.0), "W", (20.0, 30.0, 0.0)
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16)).save(buffer, "JPEG", quality=85, exif=exif.tobytes())
    entry = CATALOG.by_path["jpg/exif-gps-640x480.jpg"]
    props = validate(buffer.getvalue(), entry, CATALOG.mime_for(entry)).props
    assert (props["gps_latitude"], props["gps_longitude"]) == (-10.0, -20.5)


def test_the_webp_codec_reader_tells_the_two_bitstreams_and_an_animation_apart(built) -> None:
    lossy = build("webp/lossless-640x480.webp", Path(tempfile.mkdtemp()), quality=80)
    assert _webp_codecs(lossy) == {"lossy"}
    assert _webp_codecs(built["webp/lossless-640x480.webp"]) == {"lossless"}
    assert _webp_codecs(built["webp/animated-10frames-256x256.webp"]) == {"lossless"}, "in ANMF"


def test_the_jpeg_quality_reader_finds_the_quality_a_file_was_written_at(built) -> None:
    assert _jpeg_quality(built["jpg/quality-10-640x480.jpg"]) == 10
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, "JPEG", quality=73)
    assert _jpeg_quality(buffer.getvalue()) == 73, "another quality is read as itself"


# --- what the new props and checks leave alone ----------------------------------------------

#: Published before this batch and built here: their measured props must not move.
BEFORE = (
    "png/1x1.png",
    "png/100x100.png",
    "png/640x480.png",
    "png/1920x1080.png",
    "png/transparent-256x256.png",
    "png/grayscale-512x512.png",
    "png/animated-apng-10frames-128x128.png",
    "png/1mb.png",
    "jpg/100x100.jpg",
    "jpg/640x480.jpg",
    "jpg/1920x1080.jpg",
    "jpg/progressive-1920x1080.jpg",
    "jpg/cmyk-640x480.jpg",
    "jpg/cmyk-640x640.jpg",
    "jpg/exif-orientation-6-640x480.jpg",
    "jpg/exif-orientation-8-640x480.jpg",
    "gif/1x1.gif",
    "gif/animated-10frames-256x256.gif",
    "webp/lossy-640x480.webp",
    "webp/alpha-256x256.webp",
    "svg/simple-shapes.svg",
    "svg/with-embedded-png.svg",
    "bmp/24bit-256x256.bmp",
    "tiff/rgb-640x480.tiff",
    "tiff/lzw-640x480.tiff",
    "tiff/16bit-gray-big-endian-640x480.tiff",
    "ico/favicon-16-32-48.ico",
)


@pytest.mark.parametrize("path", BEFORE)
def test_a_published_files_bytes_and_props_are_what_they_were(path, tmp_path) -> None:
    """No key appears and none changes, and the generators still write the same bytes:
    every new prop is reported only where it applies."""
    entry = CATALOG.by_path[path]
    data = build(path, tmp_path)
    assert hashlib.sha256(data).hexdigest() == MANIFEST[path]["sha256"]
    report = validate(data, entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures
    assert report.props == MANIFEST[path]["props"]


def test_the_avif_props_are_what_they_were_and_its_bytes_are_cpu_dependent_so_not_compared(
    tmp_path,
) -> None:
    """Its encoder may choose kernels by CPU, so CI's bytes are the published ones (docs/06 §4);
    what is checked here is that the generator still produces a file the validator reads the
    same way."""
    path = "avif/640x480.avif"
    entry = CATALOG.by_path[path]
    report = validate(build(path, tmp_path), entry, CATALOG.mime_for(entry))
    assert report.ok and report.props == MANIFEST[path]["props"]


def test_the_control_would_notice_a_prop_that_moved(tmp_path) -> None:
    """The comparison above is not vacuously equal: add one key and it differs."""
    path = "png/640x480.png"
    entry = CATALOG.by_path[path]
    props = validate(build(path, tmp_path), entry, CATALOG.mime_for(entry)).props
    assert props == MANIFEST[path]["props"]
    assert {**props, "interlaced": False} != MANIFEST[path]["props"]


# --- the claims in the descriptions, each pinned to the fact that makes it true -------------


def levels(data: bytes) -> set[int]:
    with Image.open(io.BytesIO(data)) as picture:
        return set(picture.get_flattened_data())


def test_the_16_bit_png_uses_the_whole_range_and_the_old_ramp_did_not(built) -> None:
    data = built["png/16bit-256x256.png"]
    used = levels(data)
    assert len(used) > 256 and min(used) == 0 and max(used) == 65535
    assert len({value & 0xFF for value in used}) > 1, "the low byte carries information"
    # Control: the ramp this branch used to write, an 8-bit gradient in a 16-bit container.
    old = Image.linear_gradient("L").resize((256, 256)).convert("I;16")
    assert len(set(old.get_flattened_data())) <= 256


def test_the_interlaced_png_is_adam7_and_decodes_to_the_plain_test_card(built) -> None:
    data = built["png/interlaced-512x512.png"]
    assert data[28] == 1, "IHDR's interlace method is Adam7"
    with Image.open(io.BytesIO(data)) as decoded:
        decoded.load()
        card = image_generators.test_card(512, 512, "RGB")
        assert ImageChops.difference(decoded.convert("RGB"), card).getbbox() is None
    plain = build(
        "png/interlaced-512x512.png",
        Path(tempfile.mkdtemp()),
        "image.testcard",
        width=512,
        height=512,
        fmt="PNG",
    )
    assert plain[28] == 0, "control: the plain file is not interlaced"


def test_testcard_refuses_an_interlace_it_cannot_write(tmp_path) -> None:
    """Pillow writes the interlace flag as 0 whatever it is asked. The option used to be
    accepted and ignored, so a file under an interlaced name was a plain one."""
    with pytest.raises(ValueError, match="png_interlaced"):
        build("png/640x480.png", tmp_path, interlaced=True)


def test_a_tiny_image_still_gets_an_interlaced_encoding_that_decodes(tmp_path) -> None:
    """A 3 by 2 image has empty Adam7 passes, which are left out rather than written empty."""
    out = image_generators.png_interlaced(
        GeneratorContext(path="png/x.png", workdir=tmp_path), width=3, height=2
    )
    with Image.open(io.BytesIO(out)) as decoded:
        decoded.load()
        card = image_generators.test_card(3, 2, "RGB")
        assert ImageChops.difference(decoded.convert("RGB"), card).getbbox() is None


def test_the_indexed_png_holds_at_most_sixty_four_colours(built) -> None:
    data = built["png/indexed-8bit-256x256.png"]
    with Image.open(io.BytesIO(data)) as picture:
        assert len(picture.getcolors()) <= 64
    assert MANIFEST["png/indexed-8bit-256x256.png"]["props"]["palette_entries"] == 64


@pytest.mark.parametrize("orientation", [1, 3])
def test_a_viewer_that_honours_the_tag_gets_the_upright_card_and_one_that_ignores_it_may_not(
    orientation, built
) -> None:
    path = f"jpg/exif-orientation-{orientation}-640x480.jpg"
    upright = image_generators.test_card(640, 480, "RGB", label=f"UP orientation={orientation}")
    with Image.open(io.BytesIO(built[path])) as stored:
        stored.load()
        honoured = ImageStat.Stat(ImageChops.difference(ImageOps.exif_transpose(stored), upright))
        ignored = ImageStat.Stat(ImageChops.difference(stored.convert("RGB"), upright))
    assert max(honoured.mean) < 8, "the tag restores the upright card"
    if orientation == 1:
        assert max(ignored.mean) < 8, "orientation 1 needs no rotation"
    else:
        assert max(ignored.mean) > 20, "control: without the tag the card is upside down"


def test_the_quality_10_card_is_about_half_the_size_of_the_quality_85_one(built) -> None:
    ratio = len(built["jpg/quality-10-640x480.jpg"]) / MANIFEST["jpg/640x480.jpg"]["bytes"]
    assert 0.4 < ratio < 0.6, ratio


def test_the_gps_file_is_null_island_and_no_other_published_jpeg_has_a_position() -> None:
    props = MANIFEST["jpg/exif-gps-640x480.jpg"]["props"]
    assert (props["gps_latitude"], props["gps_longitude"]) == (0.0, 0.0)
    assert props["exif_datetime_original"] == "2020:01:01 00:00:00"
    others = [
        path
        for path, entry in MANIFEST.items()
        if path.startswith("jpg/")
        and path != "jpg/exif-gps-640x480.jpg"
        and "gps_latitude" in entry["props"]
    ]
    assert others == []


def test_half_the_transparent_gif_is_transparent_and_the_other_half_is_not(built) -> None:
    data = built["gif/transparent-256x256.gif"]
    props = MANIFEST["gif/transparent-256x256.gif"]["props"]
    assert props["transparent_pixels"] == 256 * 256 // 2
    with Image.open(io.BytesIO(data)) as picture:
        rgba = picture.convert("RGBA")
        alphas = set(rgba.getchannel("A").get_flattened_data())
    assert alphas == {0, 255}, "GIF transparency is on or off, with no partial alpha"
    # gif.md says a decoder that ignores transparency shows the transparent half as black, and
    # the other half as it is: what such a decoder shows is the palette colour of that index.
    with Image.open(io.BytesIO(data)) as picture:
        flat = picture.convert("RGB")
    assert flat.crop((128, 0, 256, 256)).getextrema() == ((0, 0), (0, 0), (0, 0))
    assert flat.crop((0, 0, 128, 256)).getextrema() != ((0, 0), (0, 0), (0, 0))
    assert "transparent_pixels" not in MANIFEST["gif/animated-10frames-256x256.gif"]["props"]


def test_the_avif_alpha_file_has_partial_transparency_and_the_plain_one_has_none(built) -> None:
    with Image.open(io.BytesIO(built["avif/alpha-256x256.avif"])) as picture:
        picture.load()
        low, high = picture.getchannel("A").getextrema()
    assert low < 128 and high > 128, "an alpha ramp, not a flat channel"
    assert MANIFEST["avif/640x480.avif"]["props"]["mode"] == "RGB"


def test_the_svgs_say_what_their_descriptions_say(built) -> None:
    props = {p: MANIFEST[p]["props"] for p in PATHS if p.startswith("svg/")}
    assert props["svg/viewbox-responsive.svg"]["width"] is None
    assert props["svg/viewbox-responsive.svg"]["height"] is None
    sheet = props["svg/icons-24x24.svg"]
    assert (sheet["symbols"], sheet["uses"], sheet["symbol_viewboxes"]) == (6, 6, ["0 0 24 24"])
    text = built["svg/text-and-gradient.svg"].decode()
    assert text.count("<text") == 3
    for family in ("sans-serif", "serif", "monospace"):
        assert f'font-family="{family}"' in text
    assert props["svg/text-and-gradient.svg"]["gradients"] == 2


def test_no_new_svg_carries_script_or_an_external_reference(built) -> None:
    for path, data in built.items():
        if path.startswith("svg/"):
            text = data.decode().lower()
            assert "<script" not in text and "javascript:" not in text, path
            assert not re.search(r'href="(?!#|data:)', text), path
