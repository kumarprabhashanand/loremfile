"""The 1.7.0 batch: each file is measured, reproducible, and rejects a plausible substitute."""

from __future__ import annotations

import io
import math
import re
import struct
import zipfile
from pathlib import Path

import pytest

from loremfile import build as build_module
from loremfile.catalog import Catalog
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.util.ffmpeg import probe
from loremfile.util.zipnorm import normalize
from loremfile.validators import ValidationError, load, validate
from loremfile.validators.media import _wav_header
from loremfile.validators.text import markdown_props

PATHS = (
    "m4a/aac-64k-44k-30s.m4a",
    "opus/cbr-32k-30s.opus",
    "wav/sine-440hz-3s-48k-24bit-stereo.wav",
    "md/long-with-toc-and-footnotes.md",
    "docx/anchored-image-with-alt-text.docx",
    "hls/360p-10s/index.m3u8",
    "hls/360p-10s/seg-000.ts",
    "hls/multi-bitrate/master.m3u8",
)
CATALOG = Catalog.load()
build_module.load_generators()
load()


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    """Every fixture these tests touch, each generated once, dependencies included."""
    work = tmp_path_factory.mktemp("ranking-batch")
    cache: dict[str, bytes] = {}

    def resolve(path: str) -> bytes:
        if path not in cache:
            cache[path] = build_module.generate_one(CATALOG.by_path[path], work, resolve).data
        return cache[path]

    for path in PATHS:
        resolve(path)
    return cache


def fresh(path: str, directory: Path, made: dict[str, bytes], **overrides: object) -> bytes:
    """Generate again in a directory of its own, optionally with different parameters."""
    entry = CATALOG.by_path[path]
    context = GeneratorContext(path=path, workdir=directory)
    context._dependency = made.__getitem__  # type: ignore[assignment]
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **(entry.params | overrides))
    return out if isinstance(out, bytes) else out.read_bytes()


def check(path: str, data: bytes):
    entry = CATALOG.by_path[path]
    return validate(data, entry, CATALOG.mime_for(entry))


@pytest.mark.container
@pytest.mark.parametrize("path", PATHS)
def test_each_file_validates_and_reproduces_in_a_fresh_directory(
    path: str, made: dict[str, bytes], tmp_path: Path
) -> None:
    report = check(path, made[path])
    assert report.ok, report.failures
    assert fresh(path, tmp_path, made) == made[path]


# --- audio: rates measured from the packets, not the encoder's word ---------------------


def test_a_variable_rate_opus_is_not_the_constant_rate_file(
    made: dict[str, bytes], tmp_path: Path
) -> None:
    path = "opus/cbr-32k-30s.opus"
    assert check(path, made[path]).props["bitrate_kbps"] == 32.0
    variable = check(path, fresh(path, tmp_path, made, constant=False))
    assert variable.props["bitrate_kbps"] > 40, "libopus overshoots a pure tone when variable"
    assert any("bitrate_kbps" in failure for failure in variable.failures)


def test_the_published_rate_ignores_a_header_that_declares_another(
    made: dict[str, bytes], tmp_path: Path
) -> None:
    """Vorbis writes a nominal 128 kbps into its header; the packets average far less."""
    data = fresh("ogg/vorbis-30s.ogg", tmp_path, made)
    with (tmp_path / "v.ogg").open("wb") as handle:
        handle.write(data)
    nominal = int(probe(tmp_path / "v.ogg")["streams"][0]["bit_rate"]) / 1000
    measured = check("ogg/vorbis-30s.ogg", data).props["bitrate_kbps"]
    assert nominal == 128.0
    assert measured < nominal / 2


def test_a_48k_m4a_is_rejected_as_the_44k_one(made: dict[str, bytes], tmp_path: Path) -> None:
    data = fresh("m4a/aac-30s.m4a", tmp_path, made)
    report = check("m4a/aac-64k-44k-30s.m4a", data)
    assert any("sample_rate" in failure for failure in report.failures)


# --- WAV: bit depth and the header that carries it ---------------------------------------


def test_the_24bit_wav_has_the_extensible_header_and_a_16bit_one_is_rejected(
    made: dict[str, bytes], tmp_path: Path
) -> None:
    path = "wav/sine-440hz-3s-48k-24bit-stereo.wav"
    props = check(path, made[path]).props
    assert (props["bit_depth"], props["header_format"], props["header_bytes"]) == (
        24,
        "extensible",
        68,
    )
    assert made[path][props["header_bytes"] - 8 : props["header_bytes"] - 4] == b"data"
    sixteen = check(path, fresh(path, tmp_path, made, bits=16))
    assert {"bit_depth", "header_format", "header_bytes"} <= {
        failure.split(":")[0].removeprefix("expect.") for failure in sixteen.failures
    }


def test_a_wav_whose_data_comes_before_its_format_is_refused(made: dict[str, bytes]) -> None:
    data = made["wav/sine-440hz-3s-48k-24bit-stereo.wav"]
    assert _wav_header(data) == {"header_format": "extensible", "header_bytes": 68}
    fmt_size = struct.unpack("<I", data[16:20])[0]
    fmt_chunk = data[12 : 20 + fmt_size]
    with pytest.raises(ValidationError, match="before any fmt chunk"):
        _wav_header(data[:12] + data[20 + fmt_size :] + fmt_chunk)


# --- Markdown: every contents link and footnote resolves -------------------------------


def test_the_long_markdown_resolves_every_link_and_footnote(made: dict[str, bytes]) -> None:
    text = made["md/long-with-toc-and-footnotes.md"].decode()
    assert markdown_props(text) == {"headings": 18, "anchor_links": 16, "footnotes": 6}


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda t: t.replace("\n## 3. ", "\n## Three. ", 1), "name no heading"),
        (lambda t: re.sub(r"\n\[\^6\]: [^\n]*", "", t), "without both"),
        (lambda t: t + "\n[^7]: An orphan body.\n", "without both"),
    ],
    ids=["heading renamed", "footnote body removed", "orphan footnote body"],
)
def test_a_broken_contents_link_or_footnote_is_refused(
    made: dict[str, bytes], damage, message: str
) -> None:
    text = damage(made["md/long-with-toc-and-footnotes.md"].decode())
    with pytest.raises(ValidationError, match=message):
        markdown_props(text)


def test_a_heading_inside_a_fence_is_not_a_heading() -> None:
    assert markdown_props("```\n# not a heading\n```\n")["headings"] == 0


# --- DOCX: an anchored drawing with alt text --------------------------------------------


def _rewrite(data: bytes, change) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            body = source.read(info.filename)
            if info.filename == "word/document.xml":
                body = change(body.decode()).encode()
            target.writestr(info, body)
    return normalize(out.getvalue())


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (lambda xml: re.sub(r' descr="[^"]*"', "", xml), "images_with_alt_text"),
        (
            lambda xml: xml.replace("<wp:anchor ", "<wp:inline ").replace(
                "</wp:anchor>", "</wp:inline>"
            ),
            "anchored_images",
        ),
    ],
    ids=["alt text removed", "anchor renamed inline"],
)
def test_a_docx_without_the_anchor_or_the_alt_text_is_rejected(
    made: dict[str, bytes], change, field: str
) -> None:
    path = "docx/anchored-image-with-alt-text.docx"
    report = check(path, _rewrite(made[path], change))
    assert any(failure.startswith(f"expect.{field}") for failure in report.failures)


def test_the_inline_image_docx_is_rejected_as_the_anchored_one(
    made: dict[str, bytes], tmp_path: Path
) -> None:
    with_images = fresh("docx/with-images.docx", tmp_path, made | _pngs(tmp_path, made))
    report = check("docx/anchored-image-with-alt-text.docx", with_images)
    assert any(failure.startswith("expect.anchored_images") for failure in report.failures)


def _pngs(tmp_path: Path, made: dict[str, bytes]) -> dict[str, bytes]:
    return {
        path: build_module.generate_one(CATALOG.by_path[path], tmp_path).data
        for path in ("png/100x100.png", "png/640x480.png")
        if path not in made
    }


# --- HLS: the master is derived from its renditions' bytes -----------------------------


def test_the_master_attributes_match_an_independent_measurement(
    made: dict[str, bytes], tmp_path: Path
) -> None:
    master = made["hls/multi-bitrate/master.m3u8"].decode()
    props = check("hls/multi-bitrate/master.m3u8", made["hls/multi-bitrate/master.m3u8"]).props
    for variant, bandwidth, resolution, codecs in zip(
        ("360p-10s", "720p-10s"),
        props["bandwidths"],
        props["resolutions"],
        props["codecs"],
        strict=True,
    ):
        playlist = made[f"hls/{variant}/index.m3u8"].decode()
        seconds = [float(s) for s in re.findall(r"#EXTINF:([0-9.]+),", playlist)]
        sizes = [len(made[f"hls/{variant}/seg-{i:03d}.ts"]) for i in range(len(seconds))]
        assert bandwidth == max(math.ceil(b * 8 / s) for b, s in zip(sizes, seconds, strict=True))
        (tmp_path / "s.ts").write_bytes(made[f"hls/{variant}/seg-000.ts"])
        streams = probe(tmp_path / "s.ts")["streams"]
        video = next(s for s in streams if s["codec_type"] == "video")
        assert resolution == f"{video['width']}x{video['height']}"
        assert video["profile"] == "High" and codecs.startswith("avc1.64")
        assert int(codecs[9:11], 16) == video["level"]
        assert codecs.endswith(",mp4a.40.2")
        assert f"../{variant}/index.m3u8" in master


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda t: t.replace(',CODECS="avc1.64001e,mp4a.40.2"', "", 1), "without CODECS"),
        (
            lambda t: t.replace(
                "../360p-10s/index.m3u8", "https://loremfile.dev/hls/360p-10s/index.m3u8"
            ),
            "rendition URI",
        ),
        (lambda t: "\n".join(t.splitlines()[:4]) + "\n", "at least two"),
        (lambda t: t + "#EXT-X-ENDLIST\n", "media-playlist tag"),
    ],
    ids=["no codecs", "absolute uri", "one rendition", "endlist"],
)
def test_a_damaged_master_is_refused(made: dict[str, bytes], damage, message: str) -> None:
    text = damage(made["hls/multi-bitrate/master.m3u8"].decode())
    report = check("hls/multi-bitrate/master.m3u8", text.encode())
    assert any(message in failure for failure in report.failures), report.failures
