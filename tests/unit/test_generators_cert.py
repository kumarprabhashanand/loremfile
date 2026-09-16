"""M3.7 certificates: a self-signed Ed25519 certificate, its DER form, and a CSR.

Two properties matter more than the parsing. The key is derived from a **published** seed,
so anyone can rebuild it and check the signature — that is what makes the fixture useful
rather than opaque. And the private key is never written into a fixture: the negative test
below feeds the validator a file that carries one, so the refusal is demonstrated rather
than assumed.
"""

from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from loremfile.catalog import Catalog, Fixture
from loremfile.generators import cert as cert_generators
from loremfile.generators.base import REGISTRY, GeneratorContext
from loremfile.util.determinism import deterministic
from loremfile.validators import cert as cert_validators  # noqa: F401 - registers them
from loremfile.validators import validate

CATALOG = Catalog.load()
WORKDIR = Path(tempfile.gettempdir())
CERT_PEM = "pem/self-signed-ed25519-cert.pem"
CERT_DER = "der/self-signed-ed25519-cert.der"
PATHS = [CERT_PEM, CERT_DER]


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
    assert not report.ok, f"{path} accepted a file it should refuse"
    return " | ".join(report.failures)


def test_the_certificate_formats_are_catalogued() -> None:
    """Empty-set control: the parametrised tests below check nothing without these rows."""
    assert all(path in CATALOG.by_path for path in PATHS)


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path)
def test_a_certificate_is_byte_identical_on_a_second_build(path: str) -> None:
    """Ed25519 signs deterministically (RFC 8032), and every other input is fixed."""
    assert build(path) == build(path)


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path)
def test_a_certificate_validates_against_its_catalog_entry(path: str) -> None:
    assert check(path)["has_private_key"] is False


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path)
def test_no_fixture_carries_a_private_key(path: str) -> None:
    assert b"PRIVATE KEY" not in build(path)


def test_the_published_seed_rebuilds_the_key_that_signed_the_certificate() -> None:
    """The point of a published seed: the signature can be checked by anyone."""
    certificate = x509.load_pem_x509_certificate(build(CERT_PEM))
    public_key = cert_generators.private_key().public_key()
    certificate.public_key().verify(certificate.signature, certificate.tbs_certificate_bytes)
    assert certificate.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ) == public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def test_the_pem_and_der_files_are_the_same_certificate() -> None:
    pem = x509.load_pem_x509_certificate(build(CERT_PEM))
    der = x509.load_der_x509_certificate(build(CERT_DER))
    assert pem == der
    assert pem.public_bytes(serialization.Encoding.DER) == build(CERT_DER)


def test_the_certificate_names_only_the_reserved_host() -> None:
    props = check(CERT_PEM)
    assert props["subject_cn"] == "fixture.example"
    assert props["dns_names"] == ["fixture.example"]
    assert "loremfile.dev" not in build(CERT_PEM).decode("ascii", "replace")


def test_the_validity_window_and_serial_are_fixed() -> None:
    certificate = x509.load_pem_x509_certificate(build(CERT_PEM))
    assert certificate.serial_number == cert_generators.SERIAL
    assert certificate.not_valid_before_utc == dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    assert certificate.not_valid_after_utc == dt.datetime(2120, 1, 1, tzinfo=dt.UTC)


# --- negative tests --------------------------------------------------------


def test_a_file_carrying_a_private_key_is_refused() -> None:
    key = cert_generators.private_key().private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    assert "private key" in refused(CERT_PEM, build(CERT_PEM) + key)


def test_a_certificate_for_another_name_is_refused() -> None:
    # Built inside the guard, as a generator runs: `util.determinism` replaces
    # `datetime.datetime`, and `cryptography` checks its arguments with `isinstance`.
    with deterministic(b"a-certificate-for-another-name.."):
        other = _certificate_for("loremfile.dev")
    assert "reserved" in refused(CERT_PEM, other)


def _certificate_for(name: str) -> bytes:
    key = cert_generators.private_key()
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, name)]))
        .issuer_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, name)]))
        .public_key(key.public_key())
        .serial_number(cert_generators.SERIAL)
        .not_valid_before(cert_generators.validity()[0])
        .not_valid_after(cert_generators.validity()[1])
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .sign(key, None)
    )
    return certificate.public_bytes(serialization.Encoding.PEM)


def test_bytes_that_are_not_a_certificate_are_refused() -> None:
    assert "not a readable" in refused(CERT_DER, b"\x30\x82 not a certificate")
