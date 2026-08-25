"""Token verification: dev JWT shim plus an OIDC/JWKS verifier skeleton.

Identity invariant #7: tokens are validated against cached signing keys only.
Neither verifier ever calls IdP userinfo or introspection endpoints; the OIDC
path talks exclusively to a cached JWKS client.

The dev shim is hard-gated to ``env="dev"`` so it can never be constructed in
a production process, even by accident.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

import jwt
from jwt.exceptions import PyJWKClientError

from app.domain.models import UserCtx


@runtime_checkable
class TokenVerifier(Protocol):
    """Anything that can turn a raw bearer token into an identity context."""

    def verify(self, token: str) -> UserCtx: ...


def _uuid_claim(value: Any) -> UUID:
    """Parse one uuid-valued JWT claim; anything malformed is an invalid token."""
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise jwt.InvalidTokenError("malformed uuid claim") from exc


def _user_ctx_from_claims(claims: dict[str, Any]) -> UserCtx:
    """Map verified claims onto the pure domain identity object."""
    department_raw = claims.get("department_id")
    return UserCtx(
        sub=str(claims["sub"]),
        tenant_id=_uuid_claim(claims["tenant_id"]),
        department_id=_uuid_claim(department_raw) if department_raw is not None else None,
        role=str(claims["role"]),
        clearance_rank=int(claims["clearance_rank"]),
        visible_department_ids=(),
    )


class DevJWTVerifier:
    """HS256 shared-secret shim for local development only.

    Constructing one outside ``env="dev"`` raises immediately - the shim must
    be structurally impossible to ship to prod, not merely discouraged.
    """

    def __init__(
        self,
        secret: str,
        *,
        env: Literal["dev", "prod"],
        audience: str = "docmgmt-api",
        algorithm: str = "HS256",
    ) -> None:
        if env != "dev":
            msg = "dev token verifier forbidden outside dev"
            raise RuntimeError(msg)
        self._secret = secret
        self._audience = audience
        self._algorithm = algorithm

    def verify(self, token: str) -> UserCtx:
        claims = jwt.decode(
            token,
            self._secret,
            algorithms=[self._algorithm],
            audience=self._audience,
            options={"require": ["exp", "sub", "tenant_id", "role", "clearance_rank"]},
        )
        return _user_ctx_from_claims(claims)


def issue_dev_token(
    sub: str,
    tenant_id: str | UUID,
    department_id: str | UUID | None,
    role: str,
    clearance_rank: int,
    *,
    expires_in: int = 900,
    audience: str,
    secret: str,
) -> str:
    """Mint a short-lived dev token; tests and e2e harnesses share this minter."""
    now = datetime.now(tz=UTC)
    claims: dict[str, Any] = {
        "sub": sub,
        "tenant_id": str(tenant_id),
        "department_id": str(department_id) if department_id is not None else None,
        "role": role,
        "clearance_rank": clearance_rank,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "aud": audience,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


class OidcJwksVerifier:
    """OIDC bearer verification against a cached JWKS (issuer e.g.
    https://keycloak.example/realms/dms - config example only).

    The PyJWKClient instance is cached for the verifier's lifetime and refreshes
    its key set on unknown ``kid`` via exactly one retry; nothing else is ever
    fetched from the IdP.
    """

    def __init__(self, jwks_url: str, issuer: str, audience: str) -> None:
        self._jwk_client = jwt.PyJWKClient(jwks_url)
        self._issuer = issuer
        self._audience = audience

    def verify(self, token: str) -> UserCtx:
        header = jwt.get_unverified_header(token)
        alg = str(header.get("alg", ""))
        if alg.startswith("HS"):
            # Alg-confusion guard: reject symmetric algorithms BEFORE any key
            # fetch, so an attacker-chosen HMAC-over-a-public-key never runs.
            raise jwt.InvalidAlgorithmError(f"token algorithm {alg!r} is not accepted")
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
        except PyJWKClientError:
            # Unknown kid: force one cache refresh, retry exactly once.
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
        key_algorithm = signing_key.algorithm_name
        if key_algorithm is None:
            raise jwt.InvalidAlgorithmError("signing key carries no algorithm")
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[key_algorithm],
            issuer=self._issuer,
            audience=self._audience,
        )
        return _user_ctx_from_claims(claims)
