"""Shared fixtures for the security suite. Fully hermetic: no test touches a network."""

import pytest

DEV_SECRET = "unit-test-only-secret-0123456789abcdef"  # noqa: S105 - synthetic value, never deployed
AUDIENCE = "docmgmt-api"
# The .invalid TLD is reserved by RFC 2606 and can never resolve, so even a bug
# that reached for the real HTTP client could not leak this suite onto a network.
ISSUER = "https://idp.invalid/realms/dms"
JWKS_URL = "https://idp.invalid/realms/dms/protocol/openid-connect/certs"

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    _HAS_CRYPTOGRAPHY = True
except ModuleNotFoundError:  # pragma: no cover - depends on local extras
    _HAS_CRYPTOGRAPHY = False


@pytest.fixture
def dev_secret() -> str:
    return DEV_SECRET


@pytest.fixture
def audience() -> str:
    return AUDIENCE


@pytest.fixture
def issuer() -> str:
    return ISSUER


@pytest.fixture
def jwks_url() -> str:
    return JWKS_URL


@pytest.fixture
def rsa_signing_material() -> tuple[bytes, object, str]:
    """(private PEM for signing, public key object for verification, alg name)."""
    if not _HAS_CRYPTOGRAPHY:
        pytest.skip("cryptography not installed in this venv; RSA paths unverifiable")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem, private_key.public_key(), "RS256"
