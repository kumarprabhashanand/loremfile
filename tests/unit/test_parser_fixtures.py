"""The parser batch measures awkward properties and rejects plausible substitutes."""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest
from lxml import etree
from PIL import Image, ImageChops, ImageOps, ImageStat
from pypdf import PdfReader, PdfWriter

from loremfile.build import load_generators
from loremfile.catalog import Catalog
from loremfile.generators import archive, image, office, pdf
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.util.zipnorm import normalize
from loremfile.validators import load, validate

PATHS = (
    "jpg/exif-orientation-8-640x480.jpg",
    "mp4/non-faststart-720p-5s.mp4",
    "zip/zip64-70000-empty-files.zip",
    "pdf/scanned-1page.pdf",
    "docx/with-tracked-changes.docx",
    "txt/utf16be-no-bom.txt",
)
CATALOG = Catalog.load()
load_generators()
load()
WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def build(path: str, directory: Path, **overrides: object) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    entry = CATALOG.by_path[path]
    context = GeneratorContext(path=path, workdir=directory)
    with deterministic(context.seed):
        out = REGISTRY.get(entry.generator)(context, **(entry.params | overrides))
    return out if isinstance(out, bytes) else out.read_bytes()


def check(path: str, data: bytes):
    entry = CATALOG.by_path[path]
    return validate(data, entry, CATALOG.mime_for(entry))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("parser-fixtures")
    return {path: build(path, root / str(index)) for index, path in enumerate(PATHS)}


@pytest.mark.container
@pytest.mark.parametrize("path", PATHS)
def test_each_variant_validates_and_reproduces_in_a_fresh_directory(path, built, tmp_path):
    report = check(path, built[path])
    assert report.ok, report.failures
    assert built[path] == build(path, tmp_path)


def test_orientation_corrects_the_pixels_and_wrong_tag_is_rejected(built):
    path = PATHS[0]
    with Image.open(io.BytesIO(built[path])) as stored:
        upright = ImageOps.exif_transpose(stored)
        reference = image.test_card(640, 480, label="UP orientation=8")
        difference = ImageStat.Stat(ImageChops.difference(upright, reference))
        assert max(difference.mean) < 8, (
            "tag must restore the upright test card, not rotate it twice"
        )
        # Same readable picture and stored dimensions, but the orientation property is wrong.
        exif = stored.getexif()
        exif[274] = 1
        out = io.BytesIO()
        stored.save(out, format="JPEG", exif=exif)
    wrong = check(path, out.getvalue())
    assert not wrong.ok
    assert any("expect.exif_orientation" in failure for failure in wrong.failures)


def test_faststart_is_a_measured_property_and_wrong_layout_is_rejected(built, tmp_path):
    path = PATHS[1]
    report = check(path, built[path])
    assert report.props["faststart"] is False
    assert report.props["moov_at_end"] is True
    wrong = check(path, build(path, tmp_path, faststart=True))
    assert not wrong.ok
    assert any("expect.faststart" in failure for failure in wrong.failures)
    # The old faststart requirement still rejects the new layout.
    old = CATALOG.by_path["mp4/720p-5s.mp4"]
    assert not validate(built[path], old, CATALOG.mime_for(old)).ok


def test_missing_media_atom_is_rejected(built):
    path = PATHS[1]
    payload = built[path]
    assert b"mdat" in payload
    wrong = check(path, payload.replace(b"mdat", b"free", 1))
    assert not wrong.ok
    assert any("no mdat atom" in failure for failure in wrong.failures)


@pytest.mark.parametrize("count", [0, 65_535])
def test_zip64_generator_refuses_classic_zip_entry_counts(count, tmp_path):
    context = GeneratorContext(path=PATHS[2], workdir=tmp_path)
    with pytest.raises(ValueError, match="more than 65,535"):
        archive.zip64_empty(context, count=count)


def test_zip64_counts_the_members_and_rejects_an_ordinary_zip(built, tmp_path):
    path = PATHS[2]
    report = check(path, built[path])
    assert report.props["entries"] == report.props["zip64_entries"] == 70_000
    with zipfile.ZipFile(io.BytesIO(built[path])) as package:
        assert package.read("file-00000.txt") == package.read("file-69999.txt") == b""
    context = GeneratorContext(path=path, workdir=tmp_path)
    wrong = check(path, archive.zip_text_files(context, count=3))
    assert not wrong.ok
    assert any("ZIP64" in failure for failure in wrong.failures)


@pytest.mark.parametrize("damage", ["count", "locator", "bounds", "record", "offset", "disk"])
def test_zip64_reads_real_end_records_instead_of_inferring_them_from_a_count(built, damage):
    path = PATHS[2]
    corrupted = bytearray(built[path])
    end = corrupted.rfind(b"PK\x06\x06")
    assert end > 0
    if damage == "count":
        struct.pack_into("<Q", corrupted, end + 24, 69_999)
        struct.pack_into("<Q", corrupted, end + 32, 69_999)
    elif damage == "locator":
        locator = corrupted.rfind(b"PK\x06\x07")
        corrupted[locator : locator + 4] = b"bad!"
    elif damage == "bounds":
        struct.pack_into("<Q", corrupted, end + 48, 1)
    elif damage == "record":
        corrupted[end : end + 4] = b"bad!"
    elif damage == "offset":
        locator = corrupted.rfind(b"PK\x06\x07")
        struct.pack_into("<Q", corrupted, locator + 8, len(corrupted))
    else:
        locator = corrupted.rfind(b"PK\x06\x07")
        struct.pack_into("<I", corrupted, locator + 4, 1)
    assert not check(path, bytes(corrupted)).ok


def test_scan_has_visible_image_content_but_no_text_and_rejects_blank_pages(built, tmp_path):
    path = PATHS[3]
    reader = PdfReader(io.BytesIO(built[path]))
    assert reader.pages[0].extract_text() == ""
    assert len(reader.pages[0].images) == 1
    raster = reader.pages[0].images[0].image.convert("L")
    assert raster.getextrema() == (0, 255), "empty white pages are not scans"
    context = GeneratorContext(path=path, workdir=tmp_path)
    for payload in (pdf.blank(context, pages=1), pdf.basic(context, pages=1)):
        wrong = check(path, payload)
        assert not wrong.ok
        assert any("expect.image_only" in failure for failure in wrong.failures)


def test_scan_validator_rejects_an_image_with_a_text_layer(built, tmp_path):
    path = PATHS[3]
    writer = PdfWriter(clone_from=io.BytesIO(built[path]))
    context = GeneratorContext(path=path, workdir=tmp_path)
    text = PdfReader(io.BytesIO(pdf.basic(context, pages=1)))
    writer.pages[0].merge_page(text.pages[0])
    out = io.BytesIO()
    writer.write(out)
    wrong = check(path, out.getvalue())
    assert wrong.props["images"] == 1
    assert wrong.props["text_characters"] > 0
    assert not wrong.ok
    assert any("expect.image_only" in failure for failure in wrong.failures)


@pytest.mark.parametrize("attribute", ["id", "author", "date"])
def test_revision_metadata_is_required(built, attribute):
    path = PATHS[4]

    def remove(tree):
        revision = tree.find(".//w:ins", WORD_NS)
        del revision.attrib[f"{{{WORD_NS['w']}}}{attribute}"]

    wrong = check(path, rewrite_xml(built[path], "word/document.xml", remove))
    assert not wrong.ok
    assert any("revision lacks" in failure for failure in wrong.failures)


@pytest.mark.parametrize(
    "damage", ["revision-id", "comment-id", "missing-comment-id", "empty-comment", "empty-range"]
)
def test_revision_and_comment_structure_guards_fire(built, damage):
    path = PATHS[4]
    part = "word/document.xml" if damage in {"revision-id", "empty-range"} else "word/comments.xml"

    def mutate(tree):
        if damage == "revision-id":
            inserted = tree.find(".//w:ins", WORD_NS)
            deleted = tree.find(".//w:del", WORD_NS)
            inserted.set(f"{{{WORD_NS['w']}}}id", deleted.get(f"{{{WORD_NS['w']}}}id"))
        elif damage == "empty-range":
            start = tree.find(".//w:commentRangeStart", WORD_NS)
            end = tree.find(".//w:commentRangeEnd", WORD_NS)
            end.addprevious(start)
        else:
            comment = tree.find("w:comment", WORD_NS)
            if damage == "comment-id":
                tree.append(etree.fromstring(etree.tostring(comment)))
            elif damage == "missing-comment-id":
                del comment.attrib[f"{{{WORD_NS['w']}}}id"]
            else:
                for node in comment.findall(".//w:t", WORD_NS):
                    node.text = ""

    wrong = check(path, rewrite_xml(built[path], part, mutate))
    assert not wrong.ok
    assert any(
        message in failure
        for message in ("duplicate revision ids", "comment ids", "empty comment", "comment range")
        for failure in wrong.failures
    )


def rewrite_xml(data, part, mutate):
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        members = {name: source.read(name) for name in source.namelist()}
    tree = etree.fromstring(members[part])
    mutate(tree)
    members[part] = etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for name, payload in members.items():
            target.writestr(name, payload)
    return normalize(out.getvalue())


def test_tracked_text_distinguishes_deleted_from_current_and_rejects_plain_docx(built, tmp_path):
    path = PATHS[4]
    report = check(path, built[path])
    assert report.props["insertions"] == report.props["deletions"] == report.props["comments"] == 1
    assert "confirmed" in report.props["current_text"]
    assert "cancelled" not in report.props["current_text"]
    with zipfile.ZipFile(io.BytesIO(built[path])) as package:
        tree = etree.fromstring(package.read("word/document.xml"))
        naive = "".join(tree.itertext())
    assert "cancelled" in naive and "confirmed" in naive
    context = GeneratorContext(path=path, workdir=tmp_path)
    wrong = check(path, office.docx_basic(context, paragraphs=1))
    assert not wrong.ok


@pytest.mark.parametrize(
    "element", ["ins", "del", "commentRangeStart", "commentRangeEnd", "commentReference"]
)
def test_missing_revision_or_comment_anchor_is_rejected(built, element):
    path = PATHS[4]

    def remove(tree):
        node = tree.find(f".//w:{element}", WORD_NS)
        assert node is not None
        node.getparent().remove(node)

    wrong = rewrite_xml(built[path], "word/document.xml", remove)
    assert not check(path, wrong).ok


@pytest.mark.parametrize(
    "damage",
    ["relationship", "content-type", "deleted-text", "tracking", "comment-id", "settings-order"],
)
def test_miswired_comment_or_revision_is_rejected(built, damage):
    path = PATHS[4]
    part = {
        "relationship": "word/_rels/document.xml.rels",
        "content-type": "[Content_Types].xml",
        "tracking": "word/settings.xml",
        "settings-order": "word/settings.xml",
        "comment-id": "word/comments.xml",
    }.get(damage, "word/document.xml")

    def mutate(tree):
        if damage in {"relationship", "content-type"}:
            key = "Type" if damage == "relationship" else "ContentType"
            found = [
                node
                for node in tree
                if (node.get(key) or "").endswith(
                    "comments" if damage == "relationship" else "comments+xml"
                )
            ]
            assert len(found) == 1
            tree.remove(found[0])
        elif damage == "deleted-text":
            tree.find(".//w:delText", WORD_NS).tag = f"{{{WORD_NS['w']}}}t"
        elif damage == "tracking":
            tree.find("w:trackRevisions", WORD_NS).set(f"{{{WORD_NS['w']}}}val", "false")
        elif damage == "settings-order":
            tree.append(tree.find("w:trackRevisions", WORD_NS))
        else:
            tree.find("w:comment", WORD_NS).set(f"{{{WORD_NS['w']}}}id", "99")

    assert not check(path, rewrite_xml(built[path], part, mutate)).ok


@pytest.mark.parametrize("damage", ["bom", "little-endian", "odd-length", "empty"])
def test_bomless_utf16be_is_measured_from_code_units_and_rejects_wrong_input(built, damage):
    path = PATHS[5]
    data = built[path]
    report = check(path, data)
    assert report.props["byte_order"] == "be" and report.props["bom"] is False
    assert data.decode("utf-16be").startswith("Lorem ipsum")
    wrong = {
        "bom": b"\xfe\xff" + data,
        "little-endian": data.decode("utf-16be").encode("utf-16le"),
        "odd-length": data[:-1],
        "empty": b"",
    }[damage]
    assert not check(path, wrong).ok
