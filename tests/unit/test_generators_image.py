"""M3.3 images: generators, validators, negative tests, determinism tests.

SVG gets the most negative tests of any format in the catalog, because it is the only
one that renders as active content in a browser. A published SVG carrying a script
element or an external reference would be a real security problem, not a cosmetic one,
so both the validator and the policy scanner have to reject it.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from loremfile.build import load_generators
from loremfile.catalog import Catalog, Fixture
from loremfile.generators import image as im
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import _REGISTRY, ValidationError, load, validate

WORKDIR = Path(tempfile.gettempdir())
CATALOG = Catalog.load()
load_generators()
load()


def ctx(path: str) -> GeneratorContext:
    return GeneratorContext(path=path, workdir=WORKDIR)


def fixture(path: str) -> Fixture:
    return CATALOG.by_path[path]


def build(path: str) -> bytes:
    entry = fixture(path)
    context = ctx(path)
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **entry.params)
    assert isinstance(out, bytes)
    return out


def check(path: str) -> dict:
    entry = fixture(path)
    report = validate(build(path), entry, CATALOG.mime_for(entry))
    assert report.ok, report.failures
    return report.props


def measure(path: str, payload: bytes) -> dict:
    entry = fixture(path)
    return _REGISTRY[entry.format](payload, entry, CATALOG.mime_for(entry))


# --- the test card ---------------------------------------------------------


@pytest.mark.parametrize(("width", "height"), [(1, 1), (2, 3), (7, 7), (8, 8), (64, 64)])
def test_test_card_survives_tiny_sizes(width: int, height: int) -> None:
    """1x1 crashed the first implementation: eight colour bars in one pixel."""
    card = im.test_card(width, height)
    assert card.size == (width, height)


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "P", "CMYK", "I;16"])
def test_every_supported_mode_produces_that_mode(mode: str) -> None:
    assert im.test_card(64, 64, mode).mode == mode


def test_unsupported_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported mode"):
        im.test_card(16, 16, "YCbCr")


# --- raster fixtures -------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "width", "height"),
    [
        ("png/1x1.png", 1, 1),
        ("png/640x480.png", 640, 480),
        ("jpg/100x100.jpg", 100, 100),
        ("gif/1x1.gif", 1, 1),
        ("bmp/24bit-256x256.bmp", 256, 256),
        ("tiff/rgb-640x480.tiff", 640, 480),
    ],
)
def test_dimensions_are_what_the_name_claims(path: str, width: int, height: int) -> None:
    props = check(path)
    assert (props["width"], props["height"]) == (width, height)


def test_transparent_png_really_has_an_alpha_channel() -> None:
    props = check("png/transparent-256x256.png")
    assert props["mode"] == "RGBA"
    with Image.open(io.BytesIO(build("png/transparent-256x256.png"))) as image:
        alpha = image.getchannel("A")
        assert alpha.getextrema() != (255, 255), "a uniform alpha would test nothing"


def test_grayscale_png_is_single_channel() -> None:
    assert check("png/grayscale-512x512.png")["mode"] == "L"


def test_apng_is_animated_with_the_right_frame_count() -> None:
    props = check("png/animated-apng-10frames-128x128.png")
    assert props["animated"] is True
    assert props["frames"] == 10


def test_animated_gif_frames_actually_differ() -> None:
    """An animation whose frames are identical is not testing anything."""
    payload = build("gif/animated-10frames-256x256.gif")
    with Image.open(io.BytesIO(payload)) as image:
        assert image.n_frames == 10
        image.seek(0)
        first = image.convert("RGB").tobytes()
        image.seek(1)
        second = image.convert("RGB").tobytes()
    assert first != second


def test_progressive_jpeg_is_marked_progressive() -> None:
    assert check("jpg/progressive-1920x1080.jpg")["progressive"] is True


def test_cmyk_jpeg_is_cmyk() -> None:
    assert check("jpg/cmyk-640x480.jpg")["mode"] == "CMYK"


def test_exif_orientation_tag_is_present_and_pixels_are_rotated() -> None:
    """Orientation 6 means the stored pixels are rotated; the tag corrects them."""
    props = check("jpg/exif-orientation-6-640x480.jpg")
    assert props["exif_orientation"] == 6
    # Stored 90 degrees off, so the stored raster is portrait where the card is landscape.
    assert props["width"] == 480
    assert props["height"] == 640


def test_ico_carries_all_three_resolutions() -> None:
    assert check("ico/favicon-16-32-48.ico")["sizes"] == [16, 32, 48]


def test_avif_decodes_and_has_the_right_size() -> None:
    props = check("avif/640x480.avif")
    assert (props["width"], props["height"]) == (640, 480)


@pytest.mark.parametrize(("path", "target"), [("png/1mb.png", 10**6), ("jpg/1mb.jpg", 10**6)])
def test_sized_images_land_inside_the_tolerance(path: str, target: int) -> None:
    assert abs(len(build(path)) - target) <= 0.05 * target


# --- svg -------------------------------------------------------------------


def test_svg_is_wellformed_and_self_describing() -> None:
    props = check("svg/simple-shapes.svg")
    assert props["root_element"] == "svg"
    assert props["width"] == "200"


def test_embedded_png_svg_has_no_external_reference() -> None:
    text = build("svg/with-embedded-png.svg").decode()
    assert "data:image/png;base64," in text
    assert "http://" not in text.replace("http://www.w3.org", "")
    check("svg/with-embedded-png.svg")


@pytest.mark.parametrize(
    ("markup", "match"),
    [
        ('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "script"),
        ('<svg xmlns="http://www.w3.org/2000/svg"><rect onclick="x()"/></svg>', "event-handler"),
        ('<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:x()"/></svg>', "javascript:"),
        (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<image href="https://example.com/x.png"/></svg>',
            "external",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
            "foreignobject",
        ),
    ],
)
def test_svg_validator_rejects_active_content(markup: str, match: str) -> None:
    """The one format where a careless fixture would be a real security problem."""
    entry = fixture("svg/simple-shapes.svg")
    with pytest.raises(ValidationError, match=match):
        measure("svg/simple-shapes.svg", markup.encode())
    # And the whole pipeline must fail, not just the validator.
    report = validate(markup.encode(), entry, CATALOG.mime_for(entry))
    assert not report.ok


def test_svg_with_a_non_svg_root_is_rejected() -> None:
    with pytest.raises(ValidationError, match="not 'svg'"):
        measure("svg/simple-shapes.svg", b'<html xmlns="http://www.w3.org/2000/svg"/>')


# --- determinism -----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "png/640x480.png",
        "png/transparent-256x256.png",
        "png/animated-apng-10frames-128x128.png",
        "jpg/640x480.jpg",
        "jpg/progressive-1920x1080.jpg",
        "jpg/cmyk-640x480.jpg",
        "jpg/exif-orientation-6-640x480.jpg",
        "gif/1x1.gif",
        "gif/animated-10frames-256x256.gif",
        "webp/lossy-640x480.webp",
        "webp/alpha-256x256.webp",
        "avif/640x480.avif",
        "bmp/24bit-256x256.bmp",
        "tiff/rgb-640x480.tiff",
        "ico/favicon-16-32-48.ico",
        "svg/simple-shapes.svg",
        "svg/with-embedded-png.svg",
    ],
)
def test_running_twice_gives_identical_bytes(path: str) -> None:
    assert build(path) == build(path)


# --- negative tests --------------------------------------------------------


def test_truncated_png_is_rejected() -> None:
    entry = fixture("png/640x480.png")
    report = validate(build("png/640x480.png")[:200], entry, CATALOG.mime_for(entry))
    assert not report.ok


def test_corrupted_jpeg_body_is_rejected() -> None:
    entry = fixture("jpg/640x480.jpg")
    payload = bytearray(build("jpg/640x480.jpg"))
    payload[400:1200] = b"\x00" * 800
    report = validate(bytes(payload), entry, CATALOG.mime_for(entry))
    assert not report.ok


def test_a_png_served_as_a_jpeg_fails_the_magic_check() -> None:
    entry = fixture("jpg/640x480.jpg")
    report = validate(build("png/640x480.png"), entry, CATALOG.mime_for(entry))
    assert not report.ok
    assert any("magic" in f for f in report.failures)


def test_malformed_svg_is_rejected() -> None:
    with pytest.raises(ValidationError, match="well-formed"):
        measure("svg/simple-shapes.svg", b"<svg><rect></svg>")
