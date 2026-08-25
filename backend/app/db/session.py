"""Async engine + session factory, and the row-level-security tenant hook.

Engines are process-level singletons built lazily from ``Settings`` so that
importing this module never opens sockets and tests can inject settings.
``bind_tenant`` drives the PostgreSQL GUC that row-level security policies
read (invariant #26: tenant scoping lives in RLS, not in remembered WHEREs).
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

_TENANT_GUC_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Return the process-wide async engine, creating it on first call."""
    global _engine
    if _engine is None:
        resolved = settings if settings is not None else Settings()
        _engine = create_async_engine(resolved.database_url, echo=False)
    return _engine


def get_session_factory(
    settings: Settings | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory, creating it on first call."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(settings), expire_on_commit=False)
    return _session_factory


async def bind_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Bind the RLS tenant for the current transaction.

    Executes ``SELECT set_config('app.tenant_id', :tid, true)``; the third
    argument makes the setting transaction-scoped, so it evaporates on commit
    or rollback. MUST be called inside an active transaction (after BEGIN) -
    outside one, the binding lands on an autocommit snapshot no policy sees.
    Every new transaction must re-bind before its first tenant-scoped query.
    """
    await session.execute(_TENANT_GUC_SQL, {"tid": str(tenant_id)})
