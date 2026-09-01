"""Soft-delete of documents, in bulk, gated to the two security roles.

Deletion is a soft delete: `documents.deleted_at` is set and every existing
query already filters on it. A hard delete is neither available nor wanted —
`classifications.document_id` is a foreign key into an append-only table (#20),
and the app role holds no DELETE grant on `access_log` (#24).

Invariant #31 shapes the response: a caller must not learn whether an id they
could not delete was foreign, nonexistent, or merely denied. The route reports
only what it DID delete; everything else is silently absent.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.api.v1 import documents as documents_module

DELETE_PATH = "/v1/documents/delete"
DOC_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
FOREIGN = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def deleted(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Records what the route actually soft-deleted, and gates what it may."""
    marked: list[uuid.UUID] = []

    async def fake_deletable(
        session: Any, user: Any, document_ids: list[uuid.UUID]
    ) -> list[uuid.UUID]:
        # Only DOC_A is visible to this tenant; FOREIGN and anything unknown
        # are filtered out exactly as the real query would.
        return [d for d in document_ids if d == DOC_A]

    async def fake_delete(session: Any, document_ids: list[uuid.UUID]) -> None:
        marked.extend(document_ids)

    monkeypatch.setattr(documents_module, "_fetch_deletable_document_ids", fake_deletable)
    monkeypatch.setattr(documents_module, "_soft_delete_documents", fake_delete)
    return marked


def test_admin_can_soft_delete_a_document(client_factory: Any, deleted: Any) -> None:
    client = client_factory(role="admin")
    response = client.post(DELETE_PATH, json={"document_ids": [str(DOC_A)]})
    assert response.status_code == 200
    assert response.json()["deleted"] == [str(DOC_A)]
    assert deleted == [DOC_A]


def test_security_officer_can_delete(client_factory: Any, deleted: Any) -> None:
    client = client_factory(role="security_officer")
    assert client.post(DELETE_PATH, json={"document_ids": [str(DOC_A)]}).status_code == 200


@pytest.mark.parametrize("role", ["employee", "dept_manager", "viewer"])
def test_lower_roles_are_refused(client_factory: Any, deleted: Any, role: str) -> None:
    """Deletion hides a document from every query; it is a security action."""
    client = client_factory(role=role)
    response = client.post(DELETE_PATH, json={"document_ids": [str(DOC_A)]})
    assert response.status_code == 403
    assert deleted == [], "a refused caller still reached the delete path"


def test_unknown_ids_are_absent_from_the_response_not_reported(
    client_factory: Any, deleted: Any
) -> None:
    """#31: never reveal whether an id was foreign, missing, or denied."""
    ghost = uuid.uuid4()
    client = client_factory(role="admin")
    body = client.post(DELETE_PATH, json={"document_ids": [str(DOC_A), str(ghost)]}).json()
    assert body["deleted"] == [str(DOC_A)]
    assert str(ghost) not in str(body)
    for key in ("denied", "not_found", "missing", "errors", "failed"):
        assert key not in body, f"{key} leaks why an id was skipped (#31)"


def test_a_foreign_tenants_document_is_not_deleted(client_factory: Any, deleted: Any) -> None:
    client = client_factory(role="admin")
    body = client.post(DELETE_PATH, json={"document_ids": [str(FOREIGN)]}).json()
    assert body["deleted"] == []
    assert deleted == []


def test_delete_writes_one_audit_row_per_document(
    client_factory: Any, deleted: Any, journal: list[dict[str, Any]]
) -> None:
    """#30: the audit write shares the transaction with the action."""
    client = client_factory(role="admin")
    client.post(DELETE_PATH, json={"document_ids": [str(DOC_A)]})
    rows = [e for e in journal if e["action"] == "document.delete"]
    assert len(rows) == 1
    assert rows[0]["document_id"] == DOC_A


def test_nothing_deleted_writes_no_audit_row(
    client_factory: Any, deleted: Any, journal: list[dict[str, Any]]
) -> None:
    client = client_factory(role="admin")
    client.post(DELETE_PATH, json={"document_ids": [str(FOREIGN)]})
    assert [e for e in journal if e["action"] == "document.delete"] == []


def test_empty_selection_is_rejected(client_factory: Any, deleted: Any) -> None:
    client = client_factory(role="admin")
    assert client.post(DELETE_PATH, json={"document_ids": []}).status_code == 400


def test_oversized_selection_is_rejected(client_factory: Any, deleted: Any) -> None:
    """Bounded so one request cannot hide an entire tenant's corpus."""
    client = client_factory(role="admin")
    ids = [str(uuid.uuid4()) for _ in range(501)]
    assert client.post(DELETE_PATH, json={"document_ids": ids}).status_code == 400


def test_duplicate_ids_are_deleted_once(client_factory: Any, deleted: Any) -> None:
    client = client_factory(role="admin")
    body = client.post(DELETE_PATH, json={"document_ids": [str(DOC_A), str(DOC_A)]}).json()
    assert body["deleted"] == [str(DOC_A)]
    assert deleted == [DOC_A]
