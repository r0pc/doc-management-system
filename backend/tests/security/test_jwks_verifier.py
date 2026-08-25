"""OIDC/JWKS verifier: alg-confusion guard, cached-key happy path, single refresh retry.

Hermetic by construction: the JWKS client seam is replaced with an in-memory
fake, and every URL uses the reserved .invalid TLD so no request can escape.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from jwt.exceptions import PyJWKClientError

from app.domain.models import UserCtx
from app.security.auth import OidcJwksVerifier


class FakeJwkClient:
    """Scripted stand-in for PyJWKClient; records fetches, performs zero I/O."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def get_signing_key_from_jwt(self, token: str) -> Any:
        self.calls += 1
        outcome = self._outcomes[min(self.calls, len(self._outcomes)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _identity_claims(issuer: str, audience: str) -> dict[str, Any]:
    return {
        "sub": "user-9",
        "tenant_id": str(uuid.uuid4()),
        "department_id": None,
        "role": "viewer",
        "clearance_rank": 1,
        "iss": issuer,
        "aud": audience,
        "exp": datetime.now(tz=UTC) + timedelta(minutes=5),
    }


def _inject(verifier: OidcJwksVerifier, fake: FakeJwkClient) -> None:
    verifier._jwk_client = fake  # the injection seam is the point


def test_hs_alg_confusion_rejected_before_any_key_fetch(
    dev_secret: str, audience: str, issuer: str, jwks_url: str
) -> None:
    token = jwt.encode({"sub": "x"}, dev_secret, algorithm="HS256")
    verifier = OidcJwksVerifier(jwks_url, issuer, audience)
    fake = FakeJwkClient([SimpleNamespace(key="never", algorithm_name="HS256")])
    _inject(verifier, fake)

    with pytest.raises(jwt.InvalidAlgorithmError):
        verifier.verify(token)

    assert fake.calls == 0


def test_rs256_happy_path_verifies_against_cached_jwks(
    rsa_signing_material: tuple[bytes, object, str],
    audience: str,
    issuer: str,
    jwks_url: str,
) -> None:
    pem, public_key, alg = rsa_signing_material
    claims = _identity_claims(issuer, audience)
    token = jwt.encode(claims, pem, algorithm=alg)
    verifier = OidcJwksVerifier(jwks_url, issuer, audience)
    fake = FakeJwkClient([SimpleNamespace(key=public_key, algorithm_name=alg)])
    _inject(verifier, fake)

    ctx = verifier.verify(token)

    assert ctx == UserCtx(
        sub="user-9",
        tenant_id=uuid.UUID(claims["tenant_id"]),
        department_id=None,
        role="viewer",
        clearance_rank=1,
        visible_department_ids=(),
    )
    assert fake.calls == 1


def test_unknown_kid_triggers_exactly_one_cache_refresh_retry(
    rsa_signing_material: tuple[bytes, object, str],
    audience: str,
    issuer: str,
    jwks_url: str,
) -> None:
    pem, public_key, alg = rsa_signing_material
    token = jwt.encode(_identity_claims(issuer, audience), pem, algorithm=alg)
    verifier = OidcJwksVerifier(jwks_url, issuer, audience)
    fake = FakeJwkClient(
        [
            PyJWKClientError("simulated unknown kid"),
            SimpleNamespace(key=public_key, algorithm_name=alg),
        ]
    )
    _inject(verifier, fake)

    ctx = verifier.verify(token)

    assert ctx.sub == "user-9"
    assert fake.calls == 2


def test_persistent_jwks_failure_raises_after_single_retry(
    rsa_signing_material: tuple[bytes, object, str],
    audience: str,
    issuer: str,
    jwks_url: str,
) -> None:
    pem, _public_key, alg = rsa_signing_material
    token = jwt.encode(_identity_claims(issuer, audience), pem, algorithm=alg)
    verifier = OidcJwksVerifier(jwks_url, issuer, audience)
    fake = FakeJwkClient(
        [PyJWKClientError("kid still unknown"), PyJWKClientError("refresh did not help")]
    )
    _inject(verifier, fake)

    with pytest.raises(PyJWKClientError):
        verifier.verify(token)

    assert fake.calls == 2
