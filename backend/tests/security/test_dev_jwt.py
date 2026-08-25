"""Dev JWT shim: roundtrip mapping, tamper rejection, expiry, audience, prod-env gate."""

import base64
import json
import uuid

import jwt
import pytest

from app.domain.models import UserCtx
from app.security.auth import DevJWTVerifier, issue_dev_token


def _mint(
    dev_secret: str,
    audience: str,
    *,
    tenant: uuid.UUID,
    dept: uuid.UUID | None,
    **overrides: object,
) -> str:
    return issue_dev_token(
        sub=str(overrides.pop("sub", "user-1")),
        tenant_id=tenant,
        department_id=dept,
        role=str(overrides.pop("role", "employee")),
        clearance_rank=int(overrides.pop("clearance_rank", 2)),
        expires_in=int(overrides.pop("expires_in", 900)),
        audience=audience,
        secret=dev_secret,
    )


def test_roundtrip_maps_claims_to_userctx(dev_secret: str, audience: str) -> None:
    tenant, dept = uuid.uuid4(), uuid.uuid4()
    token = _mint(dev_secret, audience, tenant=tenant, dept=dept)

    ctx = DevJWTVerifier(dev_secret, env="dev").verify(token)

    assert ctx == UserCtx(
        sub="user-1",
        tenant_id=tenant,
        department_id=dept,
        role="employee",
        clearance_rank=2,
        visible_department_ids=(),
    )


def test_null_department_survives_roundtrip(dev_secret: str, audience: str) -> None:
    token = _mint(dev_secret, audience, tenant=uuid.uuid4(), dept=None)

    ctx = DevJWTVerifier(dev_secret, env="dev").verify(token)

    assert ctx.department_id is None


def test_tampered_payload_is_rejected_without_resigning(dev_secret: str, audience: str) -> None:
    token = _mint(dev_secret, audience, tenant=uuid.uuid4(), dept=None)
    header, payload, signature = token.split(".")
    padded = payload + "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(padded))
    claims["sub"] = "attacker"
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()

    with pytest.raises(jwt.InvalidTokenError):
        DevJWTVerifier(dev_secret, env="dev").verify(f"{header}.{forged}.{signature}")


def test_expired_token_is_rejected(dev_secret: str, audience: str) -> None:
    token = _mint(dev_secret, audience, tenant=uuid.uuid4(), dept=None, expires_in=-10)

    with pytest.raises(jwt.ExpiredSignatureError):
        DevJWTVerifier(dev_secret, env="dev").verify(token)


def test_wrong_audience_is_rejected(dev_secret: str, audience: str) -> None:
    token = issue_dev_token(
        sub="user-1",
        tenant_id=uuid.uuid4(),
        department_id=None,
        role="viewer",
        clearance_rank=1,
        audience="other-api",
        secret=dev_secret,
    )

    with pytest.raises(jwt.InvalidAudienceError):
        DevJWTVerifier(dev_secret, env="dev").verify(token)


def test_verifier_refuses_to_construct_outside_dev(dev_secret: str) -> None:
    with pytest.raises(RuntimeError, match="forbidden outside dev"):
        DevJWTVerifier(dev_secret, env="prod")
