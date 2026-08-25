"""Fixtures for the search suite (hermetic: no Postgres, no MinIO).

Two layers mirror the established seam contract:
- SQL-shape tests compile real SQLAlchemy statements against the postgresql
  dialect — no database, no fakes.
- Endpoint/orchestrator tests monkeypatch the module-level data-access seams
  in ``app.search.hybrid`` with canned-row providers while auth, validation,
  RRF fusion and response shaping run REAL.

Overrides applied to every test app:
- ``deps.get_current_user``    -> a fixed :class:`UserCtx` (except anon client)
- ``deps.get_tenant_sessions`` -> fake opener yielding a sentinel session

The sentinel session raises on any unpatched ``execute``, proving every data
access path goes through the patched seams.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.domain.models import UserCtx
from app.main import create_app
from app.security.auth import DevJWTVerifier

# Routes capture Depends(deps.get_tenant_sessions) at import time; overrides
# must be keyed on THAT original object, never on a later monkeypatched attr.
SESSIONS_DEP = deps.get_tenant_sessions

TEST_SECRET = "unit-test-jwt-secret"  # noqa: S105 - synthetic test credential


class _FakeSession:
    """Stand-in for AsyncSession: unpatched data access fails loud."""

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def execute(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("unpatched data access hit the fake session")


SENTINEL_SESSION = _FakeSession()


def make_user(
    *,
    tenant_id: uuid.UUID | None = None,
    clearance_rank: int = 2,
    visible_department_ids: tuple[uuid.UUID, ...] = (),
    role: str = "employee",
) -> UserCtx:
    return UserCtx(
        sub=str(uuid.UUID(int=0xF00D)),
        tenant_id=tenant_id or uuid.UUID(int=0xA000),
        department_id=None,
        clearance_rank=clearance_rank,
        role=role,
        visible_department_ids=visible_department_ids,
    )


def build_app(monkeypatch: pytest.MonkeyPatch, *, user: UserCtx | None) -> FastAPI:
    """Fresh app with hermetic overrides; ``user=None`` keeps real auth."""

    @asynccontextmanager
    async def opener(tenant_id: uuid.UUID) -> AsyncIterator[object]:
        yield SENTINEL_SESSION

    app = create_app()
    if user is not None:

        async def current_user() -> UserCtx:
            return user

        app.dependency_overrides[deps.get_current_user] = current_user
    app.dependency_overrides[SESSIONS_DEP] = lambda: opener
    return app


@pytest.fixture
def client_factory(monkeypatch: pytest.MonkeyPatch) -> Callable[..., TestClient]:
    def make(user: UserCtx | None = None) -> TestClient:
        return TestClient(build_app(monkeypatch, user=user))

    return make


@pytest.fixture
def client(client_factory: Callable[..., TestClient]) -> TestClient:
    return client_factory(user=make_user())


@pytest.fixture
def anon_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """App with REAL token verification; requests carry no bearer token."""
    monkeypatch.setattr(deps, "get_verifier", lambda: DevJWTVerifier(TEST_SECRET, env="dev"))
    return TestClient(build_app(monkeypatch, user=None))
