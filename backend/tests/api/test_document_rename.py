"""Individual and bulk document rename endpoint tests."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

import pytest

from app.api.v1 import documents as documents_module
from app.api.v1.documents import DocumentView
from tests.api.conftest import make_user

DOC_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
DOC_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
FOREIGN = uuid.UUID("33333333-3333-3333-3333-333333333333")
TENANT_ID = uuid.UUID("00000000-0000-0000-0000-00000000a000")


def _fake_view(doc_id: uuid.UUID, filename: str = "contract.pdf") -> DocumentView:
    return DocumentView(
        id=doc_id,
        tenant_id=TENANT_ID,
        department_id=None,
        level_rank=2,
        deleted_at=None,
        status="ready",
        original_filename=filename,
        created_at=datetime.datetime.now(datetime.UTC),
        level_name="Internal",
        doc_type_name="Contract",
        blob_key="primary/key",
        blob_mime="application/pdf",
        blob_size=1024,
        current_version_id=uuid.uuid4(),
        blob_sha256="abcd" * 16,
        decided_by="human",
        confidence=None,
        department_ids=frozenset(),
    )


def test_rename_single_document_happy_path(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    updated_files: dict[uuid.UUID, str] = {}

    async def fake_fetch_view(session: Any, doc_id: uuid.UUID) -> DocumentView | None:
        if doc_id == DOC_A:
            current_name = updated_files.get(DOC_A, "original.pdf")
            return _fake_view(DOC_A, current_name)
        return None

    async def fake_update_filename(session: Any, doc_id: uuid.UUID, new_filename: str) -> None:
        updated_files[doc_id] = new_filename

    audit_records: list[dict[str, Any]] = []

    async def fake_record_audit(
        session: Any,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID | None,
        actor_id: uuid.UUID,
        action: str,
        request: Any,
        detail: str | None = None,
    ) -> None:
        audit_records.append({"action": action, "document_id": document_id, "detail": detail})

    async def fake_fetch_siblings(
        session: Any, doc_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[uuid.UUID]:
        return []

    monkeypatch.setattr(documents_module, "_fetch_document_view", fake_fetch_view)
    monkeypatch.setattr(documents_module, "_update_document_filename", fake_update_filename)
    monkeypatch.setattr("app.api.deps.record_audit", fake_record_audit)
    monkeypatch.setattr(documents_module, "_fetch_content_siblings", fake_fetch_siblings)

    client = client_factory(user=make_user(role="employee", tenant_id=TENANT_ID))
    response = client.patch(
        f"/v1/documents/{DOC_A}",
        json={"filename": "  renamed_contract.pdf  "},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(DOC_A)
    assert data["filename"] == "renamed_contract.pdf"
    assert updated_files[DOC_A] == "renamed_contract.pdf"
    assert len(audit_records) == 1
    assert audit_records[0]["action"] == "document.rename"
    assert "old_filename=original.pdf" in audit_records[0]["detail"]
    assert "new_filename=renamed_contract.pdf" in audit_records[0]["detail"]


def test_viewer_cannot_rename_document(client_factory: Any) -> None:
    client = client_factory(user=make_user(role="viewer"))
    response = client.patch(f"/v1/documents/{DOC_A}", json={"filename": "new_name.pdf"})
    assert response.status_code == 403


def test_rename_cross_tenant_returns_404(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_view(session: Any, doc_id: uuid.UUID) -> DocumentView | None:
        return None  # foreign tenant resolves to None

    monkeypatch.setattr(documents_module, "_fetch_document_view", fake_fetch_view)

    client = client_factory(user=make_user(role="admin", tenant_id=TENANT_ID))
    response = client.patch(f"/v1/documents/{FOREIGN}", json={"filename": "hacked.pdf"})
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


def test_bulk_rename_happy_path(client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    updated_files: dict[uuid.UUID, str] = {}

    async def fake_deletable(
        session: Any, user: Any, document_ids: list[uuid.UUID]
    ) -> list[uuid.UUID]:
        return [d for d in document_ids if d in (DOC_A, DOC_B)]

    async def fake_fetch_view(session: Any, doc_id: uuid.UUID) -> DocumentView | None:
        if doc_id in (DOC_A, DOC_B):
            return _fake_view(doc_id, f"old_{doc_id}.pdf")
        return None

    async def fake_update_filename(session: Any, doc_id: uuid.UUID, new_filename: str) -> None:
        updated_files[doc_id] = new_filename

    audit_records: list[dict[str, Any]] = []

    async def fake_record_audit(
        session: Any,
        *,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID | None,
        actor_id: uuid.UUID,
        action: str,
        request: Any,
        detail: str | None = None,
    ) -> None:
        audit_records.append({"action": action, "document_id": document_id, "detail": detail})

    monkeypatch.setattr(documents_module, "_fetch_deletable_document_ids", fake_deletable)
    monkeypatch.setattr(documents_module, "_fetch_document_view", fake_fetch_view)
    monkeypatch.setattr(documents_module, "_update_document_filename", fake_update_filename)
    monkeypatch.setattr("app.api.deps.record_audit", fake_record_audit)

    client = client_factory(user=make_user(role="admin", tenant_id=TENANT_ID))
    response = client.post(
        "/v1/documents/bulk-rename",
        json={
            "items": [
                {"document_id": str(DOC_A), "new_filename": "prefix_A.pdf"},
                {"document_id": str(DOC_B), "new_filename": "prefix_B.pdf"},
                {"document_id": str(FOREIGN), "new_filename": "prefix_FOREIGN.pdf"},
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["renamed"] == [str(DOC_A), str(DOC_B)]
    assert updated_files[DOC_A] == "prefix_A.pdf"
    assert updated_files[DOC_B] == "prefix_B.pdf"
    assert len(audit_records) == 2
    assert {r["document_id"] for r in audit_records} == {DOC_A, DOC_B}
