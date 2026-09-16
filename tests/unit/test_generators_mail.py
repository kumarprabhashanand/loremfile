"""M3.7 mail: messages, an mbox, and the three fields that would otherwise drift.

A message records more of the machine that wrote it than anything else in the catalog: a
`Date`, a `Message-ID` usually built from the hostname, and a MIME boundary Python picks at
random. Each is pinned by the generator, and the negative tests below drive a message with
each one unpinned to show the validator notices.
"""

from __future__ import annotations

import email
import tempfile
from email.message import EmailMessage
from pathlib import Path

import pytest

from loremfile.catalog import Catalog, Fixture
from loremfile.generators import mail as mail_generators
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import mail as mail_validators  # noqa: F401 - registers them
from loremfile.validators import validate
from loremfile.validators.mail import MBOX_SEPARATOR

CATALOG = Catalog.load()
WORKDIR = Path(tempfile.gettempdir())
#: Built in CI, where the published bytes they embed are resolvable.
NEEDS_PUBLISHED = {"eml/with-attachments.eml"}


def fixture(path: str) -> Fixture:
    return CATALOG.by_path[path]


def build(path: str) -> bytes:
    entry = fixture(path)
    ctx = GeneratorContext(path=path, workdir=WORKDIR)
    with deterministic(ctx.seed):
        out = REGISTRY.get(entry.generator)(ctx, **entry.params)
    assert isinstance(out, bytes)
    return out


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
    assert not report.ok, f"{path} accepted a message it should refuse"
    return " | ".join(report.failures)


def local_paths() -> list[str]:
    return [
        f.path
        for f in CATALOG.fixtures()
        if f.format in {"eml", "mbox"} and f.path not in NEEDS_PUBLISHED
    ]


def test_the_mail_formats_are_catalogued() -> None:
    """Empty-set control: the parametrised tests below check nothing without these rows."""
    paths = {f.path for f in CATALOG.fixtures() if f.format in {"eml", "mbox"}}
    assert len(paths) == 3
    assert paths > NEEDS_PUBLISHED


@pytest.mark.parametrize("path", local_paths(), ids=lambda path: path)
def test_a_message_is_byte_identical_on_a_second_build(path: str) -> None:
    assert build(path) == build(path)


@pytest.mark.parametrize("path", local_paths(), ids=lambda path: path)
def test_a_message_validates_against_its_catalog_entry(path: str) -> None:
    check(path)


@pytest.mark.parametrize("path", local_paths(), ids=lambda path: path)
def test_every_message_carries_the_fixed_date_and_a_seeded_message_id(path: str) -> None:
    data = build(path)
    messages = [email.message_from_bytes(part) for part in _messages(data)]
    assert messages
    for message in messages:
        assert message["Date"] == mail_generators.DATE
        assert str(message["Message-ID"]).endswith(f"@{mail_generators.DOMAIN}>")


def _messages(data: bytes) -> list[bytes]:
    if MBOX_SEPARATOR.search(data):
        return [block for block in MBOX_SEPARATOR.split(data) if block.strip()]
    return [data]


@pytest.mark.parametrize("path", local_paths(), ids=lambda path: path)
def test_no_address_can_reach_a_real_mailbox(path: str) -> None:
    """Every address is at example.com, which RFC 2606 reserves for documentation."""
    text = build(path).decode("utf-8", "replace")
    addresses = [word.strip("<>,;") for word in text.split() if "@" in word and "." in word]
    assert addresses
    assert all(
        address.endswith(f"@{mail_generators.DOMAIN}")
        or address.endswith(f"@{mail_generators.DOMAIN}>")
        for address in addresses
    ), addresses


def test_the_mbox_holds_three_separated_messages() -> None:
    props = check("mbox/3-messages.mbox")
    assert props["messages"] == 3
    assert props["subjects"] == ["Message 1 of 3", "Message 2 of 3", "Message 3 of 3"]
    assert build("mbox/3-messages.mbox").startswith(b"From alex@example.com ")


# --- negative tests --------------------------------------------------------


def test_a_message_dated_by_the_clock_is_refused() -> None:
    message = EmailMessage()
    message["Date"] = "Tue, 16 Sep 2026 07:00:00 +0000"
    message["Message-ID"] = "<abc@example.com>"
    message["From"] = "a@example.com"
    message["To"] = "b@example.com"
    message["Subject"] = "Now"
    message.set_content("body\n")
    assert "Date is" in refused("eml/plain-text.eml", message.as_bytes())


def test_a_message_id_from_the_host_is_refused() -> None:
    message = EmailMessage()
    message["Date"] = mail_generators.DATE
    message["Message-ID"] = "<1234@build-runner-7.internal>"
    message["From"] = "a@example.com"
    message["To"] = "b@example.com"
    message["Subject"] = "From a real host"
    message.set_content("body\n")
    assert "not the seeded one" in refused("eml/plain-text.eml", message.as_bytes())


def test_bytes_without_a_separator_are_not_an_mbox() -> None:
    assert "not an mbox" in refused("mbox/3-messages.mbox", build("eml/plain-text.eml"))
