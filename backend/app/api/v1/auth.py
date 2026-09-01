"""Demo sign-in: email + password against the seeded demo accounts.

This is a DEV SHIM, not an authentication system. It exists so the application
has a real front door to demonstrate — one identity per role, spanning all four
security levels — instead of silently granting every visitor a Security Admin
session, which is what the frontend did before it existed.

Three things keep it from becoming a production credential path:

* ``main.py`` mounts this router only when ``settings.env == "dev"``, and every
  handler re-checks, so a mis-wired mount 404s rather than authenticating.
* The credentials live in :mod:`app.security.demo_accounts` as constants and are
  published by ``GET /v1/auth/demo-accounts``. Nothing is stored, hashed, or
  compared against the database — ``users`` has no password column.
* The token it mints is the same short-lived HS256 dev JWT the shim already
  issued, so verification stays on the one path :func:`app.api.deps.get_verifier`
  already knows (#7). Production swaps this whole surface for OIDC.

Failed sign-in returns one message for both an unknown email and a wrong
password, and :func:`app.security.demo_accounts.authenticate` does equal work in
both cases, so neither the body nor the timing enumerates accounts.
"""

from __future__ import annotations

import logging
from typing import Final, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_404_NOT_FOUND

from app.config import Settings
from app.security.auth import issue_dev_token
from app.security.demo_accounts import DEMO_ACCOUNTS, DemoAccount, authenticate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

#: A demo session outlives a demo. Short enough that a token left in a browser
#: is not a standing grant; long enough to survive a walkthrough.
SESSION_TTL_SECONDS: Final = 8 * 60 * 60

_INVALID_CREDENTIALS: Final = "Invalid email or password."


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class SessionUser(BaseModel):
    """Identity echoed back for display. The token is the authority."""

    email: str
    name: str
    role: str
    clearance_rank: int
    level_name: str
    department: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 -- a scheme name, not a secret
    expires_in: int
    user: SessionUser


class DemoAccountOut(BaseModel):
    """A demo credential, published so the login page can list and prefill it.

    The password is included on purpose: these accounts are the demo, and the
    endpoint does not exist outside a dev build.
    """

    email: str
    password: str
    name: str
    role: str
    clearance_rank: int
    level_name: str
    department: str


def _require_dev() -> Settings:
    """Refuse to behave like an auth endpoint outside dev.

    404 rather than 403: a caller learns the route does not exist here, not
    that it exists and is switched off.
    """
    settings = Settings()
    if settings.env != "dev":
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Not Found")
    return settings


def _as_out(account: DemoAccount) -> DemoAccountOut:
    return DemoAccountOut(
        email=account.email,
        password=account.password,
        name=account.display_name,
        role=account.role,
        clearance_rank=account.clearance_rank,
        level_name=account.level_name,
        department=account.department_label,
    )


@router.get("/auth/demo-accounts", response_model=list[DemoAccountOut])
def list_demo_accounts() -> list[DemoAccountOut]:
    """The accounts the login page offers, newest privilege first."""
    _require_dev()
    return [_as_out(a) for a in DEMO_ACCOUNTS]


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    settings = _require_dev()

    account = authenticate(body.email, body.password)
    if account is None:
        # Log the attempt, never the password, and never a distinguishing
        # reason — the log is not a side channel around the response.
        logger.info("demo_login_rejected", extra={"email_domain": body.email.rpartition("@")[2]})
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS)

    token = issue_dev_token(
        # The seeded oidc_sub, so provision_actor upserts ONTO the seeded user
        # row instead of creating a duplicate beside it.
        sub=account.oidc_sub,
        tenant_id=account.tenant_id,
        department_id=account.department_id,
        role=account.role,
        clearance_rank=account.clearance_rank,
        expires_in=SESSION_TTL_SECONDS,
        audience=settings.oidc_audience or "docmgmt-api",
        secret=settings.dev_jwt_secret,
    )
    logger.info("demo_login_accepted", extra={"role": account.role})
    return LoginResponse(
        access_token=token,
        expires_in=SESSION_TTL_SECONDS,
        user=SessionUser(
            email=account.email,
            name=account.display_name,
            role=account.role,
            clearance_rank=account.clearance_rank,
            level_name=account.level_name,
            department=account.department_label,
        ),
    )
