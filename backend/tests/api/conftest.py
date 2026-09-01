"""Fixtures for the API-surface suite (hermetic: no Postgres, no MinIO).

Seam contract (Wave 4 unit strategy): every handler's data access lives behind
small module-level functions in the ``app.api.v1`` modules. These tests
monkeypatch those functions with fakes while the error envelope, auth,
permission gating, cursor encoding and content-splitting logic run REAL.
Real-SQL behaviour is exercised by the Wave 5 integration suite.

Overrides applied to every test app:
- ``deps.get_current_user``   -> a fixed :class:`UserCtx` (except ``raw_client``)
- ``deps.get_tenant_sessions``-> fake opener yielding a sentinel session
- ``deps.get_settings``       -> frozen dev Settings with a small upload cap
- ``deps.get_storage``        -> real LocalStorage over tmp_path

Audit spy: ``app.api.deps.record_audit`` is replaced app-wide with an async spy
journalling ``(session, document_id, actor_id, action)`` so tests assert exact
action strings and same-session ("same transaction") writes.
"""

import sys
import types
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.config import Settings
from app.domain.models import UserCtx
from app.main import create_app
from app.security.auth import DevJWTVerifier, issue_dev_token
from app.storage.local import LocalStorage

# Routes capture Depends(deps.get_tenant_sessions) at import time; overrides
# must be keyed on THAT original object, never on a later monkeypatched attr.
SESSIONS_DEP = deps.get_tenant_sessions

TEST_SECRET = "unit-test-jwt-secret"  # noqa: S105 - synthetic test credential
TENANT_A = uuid.UUID(int=0xA000)
TENANT_B = uuid.UUID(int=0xB000)
DEPT_A = uuid.UUID(int=0xD001)
ACTOR_ID = uuid.UUID(int=0xF00D)


class _FakeSession:
    """Stand-in for AsyncSession: handlers only ever commit/rollback here."""

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def execute(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("unpatched data access hit the fake session")


# Single instance so "same session/tx" assertions compare identity.
SENTINEL_SESSION = _FakeSession()


def make_user(
    *,
    tenant_id: UUID = TENANT_A,
    department_id: UUID | None = None,
    clearance_rank: int = 2,
    role: str = "employee",
    visible_department_ids: tuple[UUID, ...] = (),
) -> UserCtx:
    return UserCtx(
        sub=str(ACTOR_ID),
        tenant_id=tenant_id,
        department_id=department_id,
        clearance_rank=clearance_rank,
        role=role,
        visible_department_ids=visible_department_ids,
    )


@pytest.fixture
def settings_override() -> Settings:
    return Settings(
        env="dev",
        storage_backend="local",
        upload_max_bytes=1_000_000,
        presign_ttl_seconds=90,
        dev_jwt_secret=TEST_SECRET,
        oidc_issuer=None,
    )


@pytest.fixture
def blob_storage(
    tmp_path: Path, settings_override: Settings, monkeypatch: pytest.MonkeyPatch
) -> LocalStorage:
    storage = LocalStorage(
        tmp_path / "blobs",
        signing_secret=settings_override.dev_jwt_secret,
        bucket_prefix=settings_override.minio_bucket_prefix,
    )
    # Spy on open to enforce invariant #1 (API never reads object bytes)
    storage.open_calls = []  # type: ignore[attr-defined]
    original_open = storage.open

    def open_spy(key: str, **kwargs: Any) -> Any:
        storage.open_calls.append(key)  # type: ignore[attr-defined]
        return original_open(key, **kwargs)

    monkeypatch.setattr(storage, "open", open_spy)
    return storage


@pytest.fixture
def journal(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Audit journal fed by a spy installed on deps.record_audit."""
    entries: list[dict[str, Any]] = []

    async def spy(
        session: Any,
        *,
        # tenant_id is non-optional: access_log.tenant_id is NOT NULL and the
        # RLS WITH CHECK compares it to app.tenant_id, so an unattributed audit
        # write is rejected by the database (see migration 0005).
        tenant_id: UUID,
        document_id: UUID | None,
        actor_id: UUID | None,
        action: str,
        request: Any,
        detail: str | None = None,
    ) -> None:
        entries.append(
            {
                "session": session,
                "tenant_id": tenant_id,
                "document_id": document_id,
                "actor_id": actor_id,
                "action": action,
                "detail": detail,
            }
        )

    monkeypatch.setattr(deps, "record_audit", spy)
    return entries


@pytest.fixture
def captured_page_args(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from app.api.v1 import documents

    captured: dict[str, Any] = {}

    async def spy(session, user, after, limit_plus_one, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(documents, "_fetch_document_page", spy)
    return captured


@pytest.fixture(autouse=True)
def mock_provision_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_provision(session: Any, user: UserCtx) -> UUID:
        return ACTOR_ID

    monkeypatch.setattr(deps, "provision_actor", fake_provision)


def build_app(
    monkeypatch: pytest.MonkeyPatch,
    settings_override: Settings,
    blob_storage: LocalStorage,
    *,
    user: UserCtx | None,
) -> FastAPI:
    """Fresh app with hermetic overrides; ``user=None`` keeps real auth."""

    @asynccontextmanager
    async def opener(tenant_id: UUID) -> AsyncIterator[object]:
        yield SENTINEL_SESSION

    # Pass the same Settings that get overridden below: router mounting is a
    # construction-time decision, so dev-only routers (dev-storage, dev/token)
    # exist only when the app is BUILT with env="dev".
    app = create_app(settings_override)
    if user is not None:

        async def current_user() -> UserCtx:
            return user

        app.dependency_overrides[deps.get_current_user] = current_user
    app.dependency_overrides[SESSIONS_DEP] = lambda: opener
    app.dependency_overrides[deps.get_settings] = lambda: settings_override
    app.dependency_overrides[deps.get_storage] = lambda: blob_storage
    return app


@pytest.fixture
def client_factory(
    monkeypatch: pytest.MonkeyPatch,
    settings_override: Settings,
    blob_storage: LocalStorage,
    journal: list[dict[str, Any]],
) -> Callable[..., TestClient]:
    def make(
        user: UserCtx | None = None,
        role: str | None = None,
        **client_kwargs: Any,
    ) -> TestClient:
        resolved_user = make_user(role=role) if (user is None and role is not None) else user
        app = build_app(monkeypatch, settings_override, blob_storage, user=resolved_user)
        return TestClient(app, **client_kwargs)

    def with_document(
        blob_key: str | None = None, status: str = "ready", **user_kwargs: Any
    ) -> tuple[TestClient, uuid.UUID]:
        client = make(user=make_user(**user_kwargs))
        doc_id = uuid.uuid4()
        from datetime import UTC, datetime

        from app.api.v1.documents import DocumentView

        async def fake_view(*a: Any, **k: Any) -> DocumentView:
            return DocumentView(
                id=doc_id,
                tenant_id=TENANT_A,
                department_id=None,
                level_rank=1,
                deleted_at=None,
                status=status,
                original_filename="a.pdf",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                level_name="public",
                doc_type_name=None,
                blob_key=blob_key,
                blob_mime="application/pdf",
                blob_size=10,
                current_version_id=uuid.uuid4(),
            )

        monkeypatch.setattr("app.api.v1.documents._fetch_document_view", fake_view)
        return client, doc_id

    def with_ready_document(**user_kwargs: Any) -> tuple[TestClient, uuid.UUID]:
        return with_document(blob_key="docs-primary/t/ab/abc", status="ready", **user_kwargs)

    def foreign_document_id() -> uuid.UUID:
        doc_id = uuid.uuid4()
        from datetime import UTC, datetime

        from app.api.v1.documents import DocumentView

        async def fake_view(*a: Any, **k: Any) -> DocumentView:
            return DocumentView(
                id=doc_id,
                tenant_id=TENANT_B,
                department_id=None,
                level_rank=1,
                deleted_at=None,
                status="ready",
                original_filename="a.pdf",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                level_name="public",
                doc_type_name=None,
                blob_key="docs-primary/t/ab/abc",
                blob_mime="application/pdf",
                blob_size=10,
                current_version_id=uuid.uuid4(),
            )

        monkeypatch.setattr("app.api.v1.documents._fetch_document_view", fake_view)
        return doc_id

    make.with_ready_document = with_ready_document  # type: ignore[attr-defined]
    make.with_document = with_document  # type: ignore[attr-defined]
    make.foreign_document_id = foreign_document_id  # type: ignore[attr-defined]

    return make


@pytest.fixture
def client(client_factory: Callable[..., TestClient]) -> TestClient:
    return client_factory(user=make_user())


@pytest.fixture
def raw_client(
    monkeypatch: pytest.MonkeyPatch,
    settings_override: Settings,
    blob_storage: LocalStorage,
    journal: list[dict[str, Any]],
) -> TestClient:
    """App with REAL token verification (dev JWT) but no DB enrichment path.

    The verifier is pinned to the test secret; principals minted for these
    tests carry ``department_id=None`` so enrichment short-circuits before any
    database access.
    """
    monkeypatch.setattr(deps, "get_verifier", lambda: DevJWTVerifier(TEST_SECRET, env="dev"))
    app = build_app(monkeypatch, settings_override, blob_storage, user=None)
    return TestClient(app)


def bearer_for(
    *,
    tenant_id: UUID = TENANT_A,
    role: str = "employee",
    clearance_rank: int = 2,
    secret: str = TEST_SECRET,
) -> str:
    token = issue_dev_token(
        str(uuid.UUID(int=0x5EED)),
        tenant_id,
        None,
        role,
        clearance_rank,
        audience="docmgmt-api",
        secret=secret,
    )
    return f"Bearer {token}"


def install_worker_fake(
    monkeypatch: pytest.MonkeyPatch, *, fail_delay: bool = False
) -> list[tuple[str, str]]:
    """Inject a fake ``app.workers.tasks`` module capturing delay() calls."""
    calls: list[tuple[str, str]] = []

    class FakeChain:
        @staticmethod
        def delay(document_id: str, version_id: str) -> None:
            if fail_delay:
                msg = "broker down"
                raise RuntimeError(msg)
            calls.append((document_id, version_id))

    fake = types.ModuleType("app.workers.tasks")
    fake.process_upload_chain = FakeChain  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.workers.tasks", fake)
    return calls


def near_future(seconds: int = 90) -> datetime:
    return datetime.now(tz=UTC) + timedelta(seconds=seconds)
