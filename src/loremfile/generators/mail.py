"""Mail fixtures — RFC 822 messages and an mbox (docs/05 §3.11).

A message carries more clock and machine identity than almost anything else here: a
`Date`, a `Message-ID` usually built from the hostname, and a MIME boundary that Python
generates at random. All three are fixed below, so the same message is the same bytes
everywhere. Addresses use the reserved `example.com` domain, so nothing here can reach a
real mailbox.
"""

from __future__ import annotations

from email.message import EmailMessage, MIMEPart
from email.policy import SMTP
from typing import cast

from loremfile.generators.base import GeneratorContext, generator
from loremfile.util import lorem

#: docs/05 §3.11: one fixed date for every message.
DATE = "Wed, 01 Jan 2020 00:00:00 +0000"
DOMAIN = "example.com"  # RFC 2606 reserves it: these addresses can never be delivered
SENDER = f"Alex Fixture <alex@{DOMAIN}>"
RECIPIENT = f"Sam Sample <sam@{DOMAIN}>"


def _boundary(ctx: GeneratorContext, index: int = 0) -> str:
    """A MIME boundary from the fixture's seed: Python would otherwise pick a random one."""
    return f"loremfile-{ctx.seed.hex()[: 16 + index]}"


def _message_id(ctx: GeneratorContext, index: int = 0) -> str:
    """A Message-ID from the seed, not from the host name and the clock."""
    return f"<{ctx.seed.hex()[:24]}{index:02d}@{DOMAIN}>"


def _headers(message: EmailMessage, ctx: GeneratorContext, subject: str, index: int = 0) -> None:
    message["Date"] = DATE
    message["Message-ID"] = _message_id(ctx, index)
    message["From"] = SENDER
    message["To"] = RECIPIENT
    message["Subject"] = subject


@generator()
def plain_text(ctx: GeneratorContext) -> bytes:
    """The simplest possible message: headers and one text/plain body."""
    message = EmailMessage()
    _headers(message, ctx, "A plain text message")
    message.set_content(lorem.text(ctx.rng, 2))
    return message.as_bytes(policy=SMTP)


@generator()
def multipart_alternative(ctx: GeneratorContext) -> bytes:
    """text/plain with an HTML alternative, the shape most newsletters arrive in."""
    rng = ctx.rng
    body = lorem.text(rng, 2)
    message = EmailMessage()
    _headers(message, ctx, "A message in two parts")
    message.set_content(body)
    paragraphs = "".join(f"<p>{part}</p>" for part in body.split("\n\n") if part)
    message.add_alternative(f"<html><body>{paragraphs}</body></html>", subtype="html")
    message.set_boundary(_boundary(ctx))
    return message.as_bytes(policy=SMTP)


@generator()
def with_attachments(ctx: GeneratorContext, *, attachments: list[str]) -> bytes:
    """A message carrying published fixtures as attachments, read through `ctx.dependency`."""
    message = EmailMessage()
    _headers(message, ctx, "A message with attachments")
    message.set_content(lorem.text(ctx.rng, 1))
    for path in attachments:
        maintype, subtype = {"pdf": ("application", "pdf"), "png": ("image", "png")}[
            path.split("/", 1)[0]
        ]
        message.add_attachment(
            ctx.dependency(path),
            maintype=maintype,
            subtype=subtype,
            filename=path.split("/", 1)[1],
        )
    message.set_boundary(_boundary(ctx))
    return message.as_bytes(policy=SMTP)


@generator()
def inline_image(ctx: GeneratorContext, *, image: str) -> bytes:
    """An HTML body referring to an inline image by `cid:`, as mail clients embed them."""
    cid = f"image-{ctx.seed.hex()[:12]}@{DOMAIN}"
    message = EmailMessage()
    _headers(message, ctx, "A message with an inline image")
    message.set_content("This message is best read as HTML.")
    message.add_alternative(
        f'<html><body><p>{lorem.sentence(ctx.rng)}</p><img src="cid:{cid}" alt=""></body></html>',
        subtype="html",
    )
    # The HTML alternative, which the image is related to. `get_payload` is typed as a
    # union of everything a payload can be, so the part is named here rather than indexed
    # blindly into.
    parts = cast("list[MIMEPart]", message.get_payload())
    parts[1].add_related(ctx.dependency(image), maintype="image", subtype="png", cid=f"<{cid}>")
    message.set_boundary(_boundary(ctx))
    return message.as_bytes(policy=SMTP)


@generator()
def utf8_headers(ctx: GeneratorContext) -> bytes:
    """Non-ASCII in the subject and in both display names, so the encoded words matter."""
    message = EmailMessage()
    message["Date"] = DATE
    message["Message-ID"] = _message_id(ctx)
    message["From"] = f"Åsa Ödegård <asa@{DOMAIN}>"
    message["To"] = f"Jürgen Weiß <juergen@{DOMAIN}>"
    message["Subject"] = "Grüße aus München — ここにも日本語 — Ω"
    message.set_content("Unicode in the headers, plain ASCII here.\n")
    return message.as_bytes(policy=SMTP)


@generator()
def mbox(ctx: GeneratorContext, *, count: int = 3) -> bytes:
    """A Unix mbox: messages separated by `From ` lines, in mboxo form.

    Written directly rather than through `mailbox.mbox`, which needs a file on disk and
    writes the current time into the separator line.
    """
    rng = ctx.rng
    parts = []
    for index in range(count):
        message = EmailMessage()
        _headers(message, ctx, f"Message {index + 1} of {count}", index)
        message.set_content(lorem.text(rng, 1))
        body = message.as_bytes(policy=SMTP).replace(b"\r\n", b"\n")
        parts.append(b"From alex@" + DOMAIN.encode() + b" Wed Jan  1 00:00:00 2020\n" + body)
    return b"\n".join(parts) + b"\n"
