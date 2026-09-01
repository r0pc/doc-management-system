# ruff: noqa: S105
# backend/tests/integration/test_sort_pagination.py
"""Paging through a sort must return every row exactly once.

Seeds documents that are deliberately mixed: some classified, some not, so
`level` and `doc_type` are NULL for a subset. Walks every sort column in both
directions one page at a time and asserts the union of pages equals the
unpaginated set. An uncoalesced keyset predicate fails this and nothing else.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api import deps
from app.config import Settings
from app.db.models import (
    Classification,
    Department,
    DocType,
    Document,
    DocumentVersion,
    SecurityLevel,
    Tenant,
    User,
)
from app.main import create_app
from app.security.auth import DevJWTVerifier, issue_dev_token
from app.storage.local import LocalStorage

if TYPE_CHECKING:
    from tests.integration.conftest import DbTarget

pytestmark = pytest.mark.integration

SORTABLE = ["created_at", "filename", "status", "level", "doc_type"]
DEV_SECRET = "sort-pagination-secret-32bytes-long"


@pytest.fixture
def sort_settings(migrated_db: DbTarget) -> Settings:
    return Settings(
        env="dev",
        database_url=migrated_db.sqlalchemy_url,
        storage_backend="local",
        dev_jwt_secret=DEV_SECRET,
        scan_enabled=False,
    )


@pytest.fixture
def sort_client(
    sort_settings: Settings,
    migrated_db: DbTarget,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, str]:
    storage_root = (tmp_path / "sort_storage").resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    local_storage = LocalStorage(
        storage_root,
        signing_secret=sort_settings.dev_jwt_secret,
        bucket_prefix=sort_settings.minio_bucket_prefix,
    )

    monkeypatch.setenv("DATABASE_URL", sort_settings.database_url)
    monkeypatch.setattr("app.db.session._engine", None)
    monkeypatch.setattr("app.db.session._session_factory", None)
    monkeypatch.setattr("app.api.deps._storage_singleton", local_storage)
    monkeypatch.setattr(
        deps, "get_verifier", lambda: DevJWTVerifier(sort_settings.dev_jwt_secret, env="dev")
    )
    monkeypatch.setattr(deps, "get_settings", lambda: sort_settings)

    app = create_app()
    client = TestClient(app)
    return client, DEV_SECRET


@pytest.fixture
def seeded_mixed_documents(
    sync_sessions: sessionmaker[Session],
) -> tuple[list[Document], uuid.UUID, str]:
    """Seeds 8 documents: 3 unclassified, 5 classified across different levels and doc_types."""
    now = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    with sync_sessions() as session, session.begin():
        tenant = Tenant(name="Sort Test Tenant")
        session.add(tenant)
        session.flush()

        dept = Department(tenant_id=tenant.id, name="Sort Dept")
        session.add(dept)
        session.flush()

        sub = f"sort-admin-{uuid.uuid4()}"
        user = User(
            tenant_id=tenant.id,
            department_id=dept.id,
            oidc_sub=sub,
            email=f"{sub}@example.invalid",
            role="security_officer",
            clearance_rank=4,
        )
        session.add(user)
        session.flush()

        levels = list(session.execute(select(SecurityLevel)).scalars().all())
        level_map = {lvl.name.lower(): lvl.id for lvl in levels}

        doc_types = list(session.execute(select(DocType)).scalars().all())
        doc_type_map = {dt.name: dt.id for dt in doc_types}

        docs: list[Document] = []
        # Create 8 documents with varied attributes
        # Docs 0 and 1 share created_at to test ID tiebreaker
        configs = [
            ("alpha.pdf", "ready", now, None, None),
            ("bravo.pdf", "ready", now, None, None),  # identical timestamp to alpha
            ("charlie.pdf", "processing", now + timedelta(minutes=1), None, None),  # unclassified
            (
                "delta.pdf",
                "ready",
                now + timedelta(minutes=2),
                "public",
                doc_types[0].name if doc_types else None,
            ),
            (
                "echo.pdf",
                "ready",
                now + timedelta(minutes=3),
                "internal",
                doc_types[1].name if len(doc_types) > 1 else None,
            ),
            (
                "foxtrot.pdf",
                "held",
                now + timedelta(minutes=4),
                "confidential",
                doc_types[0].name if doc_types else None,
            ),
            ("golf.pdf", "ready", now + timedelta(minutes=5), "restricted", None),
            (
                "hotel.pdf",
                "failed",
                now + timedelta(minutes=6),
                "internal",
                doc_types[0].name if doc_types else None,
            ),
        ]

        for filename, status, created, lvl_name, dt_name in configs:
            doc = Document(
                tenant_id=tenant.id,
                department_id=None,
                original_filename=filename,
                status=status,
                created_at=created,
                uploaded_by=user.id,
            )
            session.add(doc)
            session.flush()

            ver = DocumentVersion(document_id=doc.id, version_no=1, created_by=user.id)
            session.add(ver)
            session.flush()

            if lvl_name is not None and lvl_name in level_map:
                cls_id = uuid.uuid4()
                cls = Classification(
                    id=cls_id,
                    document_id=doc.id,
                    version_id=ver.id,
                    level_id=level_map[lvl_name],
                    doc_type_id=doc_type_map.get(dt_name) if dt_name else None,
                    decided_by="rules",
                )
                session.add(cls)
                session.flush()
                doc.current_classification_id = cls_id
                session.flush()

            docs.append(doc)

        return docs, tenant.id, user.oidc_sub


@pytest.mark.parametrize("field", SORTABLE)
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_paging_a_sort_returns_every_row_exactly_once(
    seeded_mixed_documents: tuple[list[Document], uuid.UUID, str],
    sort_client: tuple[TestClient, str],
    field: str,
    direction: str,
) -> None:
    docs, tenant_id, sub = seeded_mixed_documents
    client, secret = sort_client
    token = issue_dev_token(
        sub,
        tenant_id,
        None,
        "security_officer",
        4,
        audience="docmgmt-api",
        secret=secret,
    )
    headers = {"Authorization": f"Bearer {token}"}

    expected = {d.id for d in docs}
    seen: list[str] = []
    cursor = None
    for _ in range(50):  # generous bound; the set is small (8 items)
        url = f"/v1/documents?sort={field}&direction={direction}&limit=2"
        if cursor:
            url += f"&cursor={cursor}"
        resp = client.get(url, headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body.get("next_cursor")
        if not cursor:
            break

    assert len(seen) == len(set(seen)), f"{field}/{direction} returned a duplicate row: {seen}"
    assert {str(i) for i in expected} == set(seen), (
        f"{field}/{direction} dropped rows. Expected {expected}, got {seen}"
    )
