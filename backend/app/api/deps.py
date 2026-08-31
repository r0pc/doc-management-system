# ruff: noqa: B008 -- Depends() in argument defaults is the FastAPI idiom;
# the Annotated[] form fails to resolve under CPython 3.14 PEP 649 lazy
# annotations with fastapi 0.141 (ForwardRef evaluation bug).


"""Request-scoped dependencies: identity, permissions, tenanted sessions, storage.

Auth (#7): bearer tokens are verified against the process-cached verifier —
``DevJWTVerifier`` when ``env=="dev"`` and no OIDC issuer is configured, the
JWKS verifier otherwise. Verification never round-trips to the IdP.

Dev department enrichment (spec §6.1): dev-JWT identities carry no visibility
set, so :func:`get_current_user` post-processes them with one recursive-CTE
query over ``departments`` to load the caller's subtree into
``UserCtx.visible_department_ids``. Principals without a department keep the
empty tuple (they see only department-less, i.e. tenant-wide, documents).
OIDC/JWKS identities are trusted to embed their own visibility claims.

Sessions (#26): handlers obtain tenanted sessions through the
:func:`get_tenant_sessions` dependency — a context-manager factory that opens
a transaction and runs ``bind_tenant`` immediately after BEGIN so RLS policies
see the caller's tenant for every statement in the block.

Audit (#30): :func:`record_audit` writes an ``access_log`` row on the session
it is handed; callers invoke it inside the same transaction as the action it
records. It is a plain function called by handlers — never middleware, never
a background task.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from functools import lru_cache
from ipaddress import ip_address
from typing import Final

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from app.config import LOCAL_ROOT_ENV, Settings, resolve_storage_root
from app.db.models import AccessLog, Department, User
from app.db.session import bind_tenant, get_session_factory
from app.domain.models import Action, UserCtx
from app.security.auth import DevJWTVerifier, OidcJwksVerifier, TokenVerifier
from app.security.permissions import role_can
from app.storage.base import Storage
from app.storage.local import LocalStorage
from app.storage.s3 import S3Storage

# Dev-only local-storage root. Honours the same override tasks.py reads
# (LOCAL_ROOT_ENV, imported from app.config) so API and worker can never
# resolve different roots — a split root 404s every download with no error
# anywhere.
DEFAULT_LOCAL_STORAGE_ROOT: Final = resolve_storage_root()

TenantSessionOpener = Callable[[uuid.UUID], AbstractAsyncContextManager[AsyncSession]]


@lru_cache(maxsize=1)
def get_verifier() -> TokenVerifier:
    """Process-wide token verifier chosen once from settings."""
    settings = Settings()
    # Falsy, not `is None`: an unset issuer can arrive as None or as "" from a
    # blank .env line, and treating "" as configured builds a JWKS client with
    # no scheme — a 500 on every authenticated request. Settings normalises
    # blanks to None; this stays defensive because the failure is silent.
    if settings.env == "dev" and not settings.oidc_issuer:
        return DevJWTVerifier(settings.dev_jwt_secret, env="dev")
    issuer = settings.oidc_issuer or ""
    jwks_url = f"{issuer.rstrip('/')}/protocol/openid-connect/certs"
    return OidcJwksVerifier(jwks_url, issuer, settings.oidc_audience or "docmgmt-api")


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization")
    if auth is None or not auth.startswith("Bearer "):
        raise jwt.InvalidTokenError("missing bearer token")
    return auth[len("Bearer ") :]


async def enrich_visible_departments(user: UserCtx) -> UserCtx:
    """Load the caller's department subtree for dev-JWT identities (§6.1)."""
    if user.department_id is None:
        return user
    factory = get_session_factory()
    async with factory() as session:
        await bind_tenant(session, user.tenant_id)
        subtree = (
            select(Department.id)
            .where(
                Department.id == user.department_id,
                Department.tenant_id == user.tenant_id,
            )
            .cte(name="dept_subtree", recursive=True)
        )
        subtree = subtree.union_all(
            select(Department.id)
            .join(subtree, Department.parent_id == subtree.c.id)
            .where(Department.tenant_id == user.tenant_id)
        )
        rows = await session.execute(select(subtree.c.id))
        visible = tuple(row[0] for row in rows)
    if user.department_id not in visible:
        visible = (user.department_id, *visible)
    return replace(user, visible_department_ids=visible)


async def get_current_user(request: Request) -> UserCtx:
    """Resolve the caller from the bearer token; 401 problem on any failure."""
    try:
        user = get_verifier().verify(_bearer_token(request))
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            HTTP_401_UNAUTHORIZED,
            "invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if isinstance(get_verifier(), DevJWTVerifier):
        return await enrich_visible_departments(user)
    return user


def require(action: Action) -> Callable[..., object]:
    """Dependency factory gating on the role->action table (#33 server-side)."""

    async def dependency(user: UserCtx = Depends(get_current_user)) -> UserCtx:
        if not role_can(user.role, action):
            raise HTTPException(HTTP_403_FORBIDDEN, "insufficient role")
        return user

    return dependency


def get_settings() -> Settings:
    """Request-scoped settings; tests override this dependency."""
    return Settings()


_storage_singleton: Storage | None = None


def build_storage(settings: Settings) -> Storage:
    """Construct the process storage backend once (local default, MinIO opt-in)."""
    global _storage_singleton
    if _storage_singleton is None:
        if settings.storage_backend == "minio":
            import boto3  # type: ignore[import-untyped]

            scheme = "https" if settings.minio_secure else "http"
            client = boto3.client(
                "s3",
                endpoint_url=f"{scheme}://{settings.minio_endpoint}",
                aws_access_key_id=settings.minio_access_key,
                aws_secret_access_key=settings.minio_secret_key,
                region_name="us-east-1",
            )
            _storage_singleton = S3Storage(client, bucket_prefix=settings.minio_bucket_prefix)
        else:
            _storage_singleton = LocalStorage(
                DEFAULT_LOCAL_STORAGE_ROOT,
                signing_secret=settings.dev_jwt_secret,
                bucket_prefix=settings.minio_bucket_prefix,
            )
    return _storage_singleton


def get_storage(settings: Settings = Depends(get_settings)) -> Storage:
    return build_storage(settings)


def get_tenant_sessions() -> TenantSessionOpener:
    """Return the real tenant-session opener; tests override this dependency."""

    @asynccontextmanager
    async def opener(tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
        # factory() autobegins on first statement; bind_tenant therefore runs
        # inside the transaction as RLS requires (#26).
        async with get_session_factory()() as session:
            await bind_tenant(session, tenant_id)
            yield session

    return opener


def _client_ip(request: Request) -> str | None:
    host = request.client.host if request.client else None
    if host is None:
        return None
    try:
        ip_address(host)
    except ValueError:
        return None  # test-client sentinels are not INET-representable
    return host


async def record_audit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    action: str,
    request: Request,
    detail: str | None = None,
) -> None:
    """Insert one access_log row on the CALLER'S session/transaction (#30).

    ``access_log`` carries bare uuids with no FKs (#24); this write must be
    awaited inside the same ``tenant_session`` block as the action itself.

    ``tenant_id`` is required, not optional: ``access_log`` is under RLS since
    0004 and NOT NULL since 0005 (#26), so a None here is no longer a nullable
    column - it is a row the database refuses and no tenant could ever read.
    Callers always have ``UserCtx.tenant_id``; the type says so.
    """
    await session.execute(
        insert(AccessLog).values(
            tenant_id=tenant_id,
            document_id=document_id,
            actor_id=actor_id,
            action=action,
            detail=detail,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            ts=datetime.now(tz=UTC),
        )
    )


async def provision_actor(session: AsyncSession, user: UserCtx) -> uuid.UUID:
    """Map an oidc_sub onto users.id, provisioning the row on first sight.

    Dev-shim behaviour pending the user-sync wave: claims are authoritative
    for role/clearance/department, so conflicts refresh those columns.
    """
    stmt = (
        pg_insert(User)
        .values(
            tenant_id=user.tenant_id,
            department_id=user.department_id,
            oidc_sub=user.sub,
            email=f"{user.sub}@oidc.local",
            role=user.role,
            clearance_rank=user.clearance_rank,
        )
        .on_conflict_do_update(
            index_elements=[User.oidc_sub],
            set_={
                "role": user.role,
                "clearance_rank": user.clearance_rank,
                "department_id": user.department_id,
            },
        )
        .returning(User.id)
    )
    row = await session.execute(stmt)
    return uuid.UUID(str(row.scalar_one()))


__all__ = [
    "LOCAL_ROOT_ENV",
    "TenantSessionOpener",
    "build_storage",
    "enrich_visible_departments",
    "get_current_user",
    "get_settings",
    "get_storage",
    "get_tenant_sessions",
    "get_verifier",
    "provision_actor",
    "record_audit",
    "require",
]
