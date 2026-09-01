# backend/tests/api/test_batch_upload.py
"""Batch cap is server-side. A client-side sum is not enforcement."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.api.v1 import uploads
from tests.api.conftest import ACTOR_ID

DEPT_ROOT = UUID(int=0xD000)

MB = 1024 * 1024
GB = 1024 * MB


def _files(*sizes: int) -> list[dict[str, Any]]:
    return [
        {"filename": f"doc{i}.pdf", "size_bytes": s, "content_type": "application/pdf"}
        for i, s in enumerate(sizes)
    ]


def patch_batch_persistence(monkeypatch: Any) -> list[dict[str, Any]]:
    inserted: list[dict[str, Any]] = []

    async def provision(session: Any, user: Any) -> UUID:
        return ACTOR_ID

    async def insert_doc(
        session: Any,
        *,
        document_id: UUID,
        user: Any,
        filename: str,
        actor_id: UUID,
        department_ids: set[UUID] | None = None,
    ) -> None:
        inserted.append(
            {
                "id": document_id,
                "filename": filename,
                "actor_id": actor_id,
                "department_ids": department_ids,
            }
        )

    async def resolve_departments(session: Any, user: Any, requested: Any) -> set[UUID]:
        # The department lookup is a real SELECT; these tests run on a fake
        # session. What it resolves to is asserted against a live database in
        # tests/api/test_document_departments.py.
        return {DEPT_ROOT}

    monkeypatch.setattr(uploads, "_provision_actor", provision)
    monkeypatch.setattr(uploads, "_insert_quarantine_document", insert_doc)
    monkeypatch.setattr(uploads, "_resolve_departments", resolve_departments)
    return inserted


def test_batch_returns_one_presigned_upload_per_file(client: Any, monkeypatch: Any) -> None:
    patch_batch_persistence(monkeypatch)
    response = client.post("/v1/uploads/batch", json={"files": _files(10, 20, 30)})
    assert response.status_code == 201
    body = response.json()
    assert len(body["uploads"]) == 3
    assert all(u["presigned_put"]["url"] for u in body["uploads"])
    assert len({u["upload_id"] for u in body["uploads"]}) == 3
    assert "batch_id" in body


def test_batch_total_over_batch_cap_is_rejected(
    client: Any,
    settings_override: Any,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(settings_override, "upload_max_bytes", 100 * MB)
    monkeypatch.setattr(settings_override, "upload_batch_max_bytes", 150 * MB)
    response = client.post("/v1/uploads/batch", json={"files": _files(90 * MB, 90 * MB)})
    assert response.status_code == 413
    assert "batch" in response.json()["detail"].lower()


def test_single_file_over_the_per_file_cap_is_rejected(client: Any) -> None:
    response = client.post("/v1/uploads/batch", json={"files": _files(200 * MB)})
    assert response.status_code == 413


def test_empty_batch_is_rejected(client: Any) -> None:
    response = client.post("/v1/uploads/batch", json={"files": []})
    assert response.status_code in (400, 422)


def test_batch_over_the_file_count_cap_is_rejected(client: Any) -> None:
    response = client.post("/v1/uploads/batch", json={"files": _files(*([1] * 501))})
    assert response.status_code == 422


def test_rejected_batch_creates_no_documents(client: Any, monkeypatch: Any) -> None:
    """A batch is all-or-nothing at intent time: no partial document rows."""
    inserted = patch_batch_persistence(monkeypatch)
    client.post("/v1/uploads/batch", json={"files": _files(*([90 * MB] * 12))})
    assert inserted == []
