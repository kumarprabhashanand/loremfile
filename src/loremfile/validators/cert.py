"""Validators for the certificate formats (docs/06 §6).

The certificate is read back with `cryptography`, its self-signature is verified against
its own public key, and the bytes are checked for the one thing that must never be there:
a private key. `validators/policy.py` refuses a PEM private key header for every fixture;
this validator says so in the certificate's own terms as well, because that is the rule a
reader of this file needs to see.
"""

from __future__ import annotations

from typing import Any

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from loremfile.catalog import Fixture
from loremfile.generators.cert import COMMON_NAME, SERIAL, validity
from loremfile.validators import ValidationError, register

PRIVATE_KEY_MARKERS = (b"PRIVATE KEY", b"BEGIN OPENSSH PRIVATE KEY")


def _no_private_key(data: bytes) -> None:
    if any(marker in data for marker in PRIVATE_KEY_MARKERS):
        raise ValidationError("contains a private key, which no fixture may ever publish")


def _describe(certificate: x509.Certificate) -> dict[str, Any]:
    public_key = certificate.public_key()
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValidationError(f"is signed with {type(public_key).__name__}, not Ed25519")
    try:
        public_key.verify(certificate.signature, certificate.tbs_certificate_bytes)
    except InvalidSignature as exc:
        raise ValidationError("does not verify against its own public key") from exc

    common_names = certificate.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
    subject_cn = str(common_names[0].value) if common_names else ""
    if subject_cn != COMMON_NAME:
        raise ValidationError(f"names {subject_cn!r}, not the reserved {COMMON_NAME!r}")
    if certificate.serial_number != SERIAL:
        raise ValidationError(f"serial is {certificate.serial_number}, not the fixed {SERIAL}")
    not_before, not_after = validity()
    if (
        certificate.not_valid_before_utc != not_before
        or certificate.not_valid_after_utc != not_after
    ):
        raise ValidationError("validity is not the fixed window, so the bytes would drift")

    names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    return {
        "subject_cn": subject_cn,
        "issuer_cn": str(
            certificate.issuer.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
        ),
        "self_signed": certificate.issuer == certificate.subject,
        "algorithm": "ed25519",
        "serial": certificate.serial_number,
        "dns_names": list(names.value.get_values_for_type(x509.DNSName)),
        "has_private_key": False,
    }


@register("pem")
def validate_pem(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
    _no_private_key(data)
    text = data.decode("ascii", "replace")
    if "-----BEGIN CERTIFICATE REQUEST-----" in text:
        try:
            request = x509.load_pem_x509_csr(data)
        except ValueError as exc:
            raise ValidationError(f"is not a readable CSR: {exc}") from exc
        if not request.is_signature_valid:
            raise ValidationError("the CSR's signature does not verify")
        common_names = request.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        return {
            "kind": "csr",
            "subject_cn": str(common_names[0].value) if common_names else "",
            "algorithm": "ed25519",
            "has_private_key": False,
        }
    try:
        certificate = x509.load_pem_x509_certificate(data)
    except ValueError as exc:
        raise ValidationError(f"is not a readable PEM certificate: {exc}") from exc
    return {"kind": "certificate", **_describe(certificate)}


@register("der")
def validate_der(data: bytes, _fixture: Fixture, _mime: str) -> dict[str, Any]:
    _no_private_key(data)
    try:
        certificate = x509.load_der_x509_certificate(data)
    except ValueError as exc:
        raise ValidationError(f"is not a readable DER certificate: {exc}") from exc
    return {"kind": "certificate", **_describe(certificate)}
