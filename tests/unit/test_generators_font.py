"""M3.7 fonts: the generated family, its four flavours, and what must never drift.

The family is generated rather than derived (ADR-018), so these tests check two things at
once: that each file is a complete, loadable font, and that nothing in it comes from the
machine that built it — `head.created` and `head.modified` are the fields a font library
fills from the clock, and they are the reason a font fixture's hash would otherwise move.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from loremfile.catalog import Catalog, Fixture
from loremfile.config import SOURCE_DATE_EPOCH
from loremfile.generators import font as font_generators
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import font as font_validators  # noqa: F401 - registers them
from loremfile.validators import validate

CATALOG = Catalog.load()
WORKDIR = Path(tempfile.gettempdir())
FONT_FORMATS = ("ttf", "otf", "woff", "woff2")
PATHS = [f"{fmt}/loremfile-sans.{fmt}" for fmt in FONT_FORMATS]


def fixture(path: str) -> Fixture:
    return CATALOG.by_path[path]


def build(path: str) -> bytes:
    entry = fixture(path)
    ctx = GeneratorContext(path=path, workdir=WORKDIR)
    with deterministic(ctx.seed):
        out = REGISTRY.get(entry.generator)(ctx, **entry.params)
    return Path(out).read_bytes()


def check(path: str, payload: bytes | None = None) -> dict:
    entry = fixture(path)
    report = validate(
        payload if payload is not None else build(path), entry, CATALOG.mime_for(entry)
    )
    assert report.ok, report.failures
    return report.props


def refused(path: str, payload: bytes) -> str:
    entry = fixture(path)
    report = validate(payload, entry, CATALOG.mime_for(entry))
    assert not report.ok, f"{path} accepted a font it should refuse"
    return " | ".join(report.failures)


def test_the_family_is_catalogued_in_all_four_flavours() -> None:
    """Empty-set control: every parametrised test below is vacuous without these rows."""
    assert {f.format for f in CATALOG.fixtures() if f.format in FONT_FORMATS} == set(FONT_FORMATS)
    assert all(path in CATALOG.by_path for path in PATHS)


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path)
def test_a_font_is_byte_identical_on_a_second_build(path: str) -> None:
    assert build(path) == build(path)


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path)
def test_a_font_validates_against_its_catalog_entry(path: str) -> None:
    props = check(path)
    assert props["units_per_em"] == 1000
    assert props["family"] == "Loremfile Sans"
    assert props["embeddable"] is True


def test_every_printable_ascii_codepoint_is_mapped() -> None:
    font = TTFont(io.BytesIO(build("ttf/loremfile-sans.ttf")))
    cmap = font.getBestCmap()
    missing = [code for code in range(0x20, 0x7F) if code not in cmap]
    assert missing == []
    assert len(cmap) == 0x7F - 0x20


def test_advance_widths_vary_so_text_has_a_rhythm() -> None:
    font = TTFont(io.BytesIO(build("ttf/loremfile-sans.ttf")))
    metrics = font["hmtx"].metrics
    widths = {metrics[font.getBestCmap()[code]][0] for code in range(0x20, 0x7F)}
    assert len(widths) > 1
    assert min(widths) >= 300


def test_the_head_timestamps_are_the_project_epoch_not_the_build_time() -> None:
    for path in PATHS:
        font = TTFont(io.BytesIO(build(path)))
        head = font["head"]
        assert head.created == head.modified == SOURCE_DATE_EPOCH + font_generators.MAC_EPOCH_OFFSET


def test_the_flavours_differ_in_bytes_and_agree_on_glyphs() -> None:
    built = {path: build(path) for path in PATHS}
    assert len(set(built.values())) == len(PATHS)
    glyph_counts = {len(TTFont(io.BytesIO(data)).getGlyphOrder()) for data in built.values()}
    assert glyph_counts == {96}
    assert len(built["woff2/loremfile-sans.woff2"]) < len(built["ttf/loremfile-sans.ttf"])


def test_outlines_are_cff_only_for_the_otf() -> None:
    assert check("otf/loremfile-sans.otf")["outlines"] == "cff"
    for path in (
        "ttf/loremfile-sans.ttf",
        "woff/loremfile-sans.woff",
        "woff2/loremfile-sans.woff2",
    ):
        assert check(path)["outlines"] == "glyf"


# --- negative tests --------------------------------------------------------


def test_a_truncated_font_is_refused() -> None:
    data = build("ttf/loremfile-sans.ttf")
    assert "not a readable font" in refused("ttf/loremfile-sans.ttf", data[: len(data) // 3])


def test_a_font_stamped_with_the_build_time_is_refused() -> None:
    """The control for the fixed timestamps: a clock-stamped font must not pass."""
    font = TTFont(io.BytesIO(build("ttf/loremfile-sans.ttf")))
    font["head"].created = font["head"].modified = 3_800_000_000
    out = io.BytesIO()
    font.save(out)
    assert "build-time stamp" in refused("ttf/loremfile-sans.ttf", out.getvalue())


def test_a_font_that_restricts_embedding_is_refused() -> None:
    font = TTFont(io.BytesIO(build("ttf/loremfile-sans.ttf")))
    # Saving a loaded font restamps `head` unless this is off, and the timestamp check
    # would then fire first — the test would pass while proving nothing about fsType.
    font.recalcTimestamp = False
    font["OS/2"].fsType = 2  # restricted licence embedding
    out = io.BytesIO()
    font.save(out)
    assert "fsType" in refused("ttf/loremfile-sans.ttf", out.getvalue())


def test_truetype_outlines_do_not_pass_as_an_otf() -> None:
    """The flavour check: the OTF row must carry CFF outlines, not glyf ones."""
    assert "no CFF table" in refused("otf/loremfile-sans.otf", build("ttf/loremfile-sans.ttf"))


def test_an_unwrapped_font_does_not_pass_as_woff() -> None:
    assert "flavour" in refused("woff/loremfile-sans.woff", build("ttf/loremfile-sans.ttf"))
