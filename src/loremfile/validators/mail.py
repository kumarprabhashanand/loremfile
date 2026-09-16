"""Validators for the mail formats (docs/06 §6).

A message is parsed back with the standard library's parser and described by what it
contains: its parts, their content types, any attachments, and whether the headers a
fixture must keep fixed are the fixed ones. The last check is the point — a `Date`,
`Message-ID` or MIME boundary taken from the machine would move the hash on every build.
"""

from __future__ import annotations

import email
import re
from email.message import Message
from typing import Any

from loremfile.catalog import Fixture
from loremfile.generators.mail import DATE
from loremfile.validators import ValidationError, register

#: An mbox message begins with a whole `From ` line (RFC 4155). The line is matched to its
#: end: splitting on the prefix alone leaves the date on the front of the first header.
MBOX_SEPARATOR = re.compile(rb"^From \S+ [^\n]*\n", re.M)


def _parts(message: Message) -> list[Message]:
    return list(message.walk()) if message.is_multipart() else [message]


def _describe(message: Message) -> dict[str, Any]:
    parts = _parts(message)
    attachments = [
        part for part in parts if part.get_content_disposition() in {"attachment", "inline"}
    ]
    return {
        "parts": len(parts),
        "content_types": sorted({part.get_content_type() for part in parts}),
        "attachments": len(attachments),
        "multipart": message.is_multipart(),
        "date": message["Date"],
        "has_message_id": bool(message["Message-ID"]),
        "subject": str(message["Subject"] or ""),
    }


def _check_fixed_headers(message: Message, path: str) -> None:
    if message["Date"] != DATE:
        raise ValidationError(f"{path}: Date is {message['Date']!r}, not the fixed {DATE!r}")
    message_id = str(message["Message-ID"] or "")
    if not message_id:
        raise ValidationError(f"{path}: has no Message-ID")
    # A Message-ID built from the host would carry its name; ours is seed-derived.
    if "@example.com>" not in message_id:
        raise ValidationError(f"{path}: Message-ID {message_id!r} is not the seeded one")


@register("eml")
def validate_eml(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    try:
        message = email.message_from_bytes(data)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"is not a readable message: {exc}") from exc
    if message.defects:
        raise ValidationError(f"the parser reported defects: {message.defects}")
    _check_fixed_headers(message, fixture.path)
    props = _describe(message)
    if props["multipart"]:
        boundary = message.get_boundary()
        if not boundary or not boundary.startswith("loremfile-"):
            raise ValidationError(f"boundary {boundary!r} is not the seeded one")
    return props


@register("mbox")
def validate_mbox(data: bytes, fixture: Fixture, _mime: str) -> dict[str, Any]:
    separators = MBOX_SEPARATOR.findall(data)
    if not separators:
        raise ValidationError("has no `From ` separator line, so it is not an mbox")
    messages = [
        email.message_from_bytes(block) for block in MBOX_SEPARATOR.split(data)[1:] if block.strip()
    ]
    if len(messages) != len(separators):
        raise ValidationError(f"{len(separators)} separators but {len(messages)} parsable messages")
    for message in messages:
        _check_fixed_headers(message, fixture.path)
    subjects = [str(message["Subject"] or "") for message in messages]
    return {
        "messages": len(messages),
        "subjects": subjects,
        "content_types": sorted({message.get_content_type() for message in messages}),
    }
