"""Certificate fixtures — a self-signed Ed25519 certificate and a CSR (docs/05 §3.12).

Two rules shape this module. **The private key is never written to a fixture**: the
content policy refuses PEM private keys outright, and a published key would be an
attractive nuisance even though this one is synthetic. And the key is derived from a fixed
public seed, so anyone can rebuild it and verify the signature — the point of a fixture is
that it is reproducible, not that it is secret.

Ed25519 signatures are deterministic by construction (RFC 8032), the serial and validity
are fixed, and the subject is always `fixture.example`: a name reserved for documentation,
never the production host.
"""

from __future__ import annotations

import datetime as dt
import hashlib

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

from loremfile.generators.base import GeneratorContext, generator

#: docs/06 §4: the seed is public on purpose, so the key is derivable and the signature
#: checkable. Nothing secret is expressed by it.
KEY_SEED = b"loremfile:cert:ed25519"
#: "Loremfile" in ASCII, as the certificate's serial number.
SERIAL = 0x4C6F72656D66696C65
COMMON_NAME = "fixture.example"
ORGANISATION = "loremfile fixtures"
#: The validity window, as parts rather than datetimes. `util.determinism` replaces
#: `datetime.datetime` for the duration of a generator, and `cryptography` checks its
#: arguments with `isinstance`: a datetime built at import time is not an instance of the
#: class in force at call time, and the builder rejects it.
NOT_BEFORE_PARTS = (2020, 1, 1)
NOT_AFTER_PARTS = (2120, 1, 1)


def validity() -> tuple[dt.datetime, dt.datetime]:
    """The fixed validity window, built against the `datetime` class in force now."""
    return (
        dt.datetime(*NOT_BEFORE_PARTS, tzinfo=dt.UTC),
        dt.datetime(*NOT_AFTER_PARTS, tzinfo=dt.UTC),
    )


def private_key() -> Ed25519PrivateKey:
    """The fixture key, derived from the public seed. Never serialised into a fixture."""
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(KEY_SEED).digest())


def _name() -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, COMMON_NAME),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, ORGANISATION),
        ]
    )


def _certificate() -> x509.Certificate:
    key = private_key()
    not_before, not_after = validity()
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name())
        .issuer_name(_name())  # self-signed: subject and issuer are the same name
        .public_key(key.public_key())
        .serial_number(SERIAL)
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(COMMON_NAME)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    )
    return builder.sign(key, None)  # Ed25519 takes no hash algorithm, and signs deterministically


@generator()
def self_signed_certificate(_ctx: GeneratorContext, *, encoding: str = "pem") -> bytes:
    """A self-signed Ed25519 certificate, PEM- or DER-encoded."""
    form = serialization.Encoding.PEM if encoding == "pem" else serialization.Encoding.DER
    return _certificate().public_bytes(form)
