"""Admin prototype upload route tests."""

from __future__ import annotations

import io
from typing import Any
from uuid import UUID

import pytest

from app.workers.scanning import ScanVerdict
from tests.api.conftest import SENTINEL_SESSION, make_user

DOC_TYPE_ID = UUID("00000000-0000-0000-0000-000000000001")
ADMIN: dict[str, object] = {"role": "admin", "clearance_rank": 4}
EMPLOYEE: dict[str, object] = {"role": "employee", "clearance_rank": 2}


def _make_sample_files(count: int) -> list[tuple[str, tuple[str, io.BytesIO, str]]]:
    files = []
    for i in range(count):
        content = f"Sample document text content {i} for prototype training."
        files.append(
            ("files", (f"sample_{i}.txt", io.BytesIO(content.encode("utf-8")), "text/plain"))
        )
    return files


def test_prototype_upload_is_gated_by_manage_taxonomy(client_factory: Any) -> None:
    client = client_factory(user=make_user(**EMPLOYEE))
    files = _make_sample_files(5)
    response = client.post(
        f"/v1/admin/doc-types/{DOC_TYPE_ID}/prototype-upload",
        files=files,
    )
    assert response.status_code == 403


def test_prototype_upload_validates_file_count(client_factory: Any) -> None:
    client = client_factory(user=make_user(**ADMIN))

    # Fewer than 5 files
    response = client.post(
        f"/v1/admin/doc-types/{DOC_TYPE_ID}/prototype-upload",
        files=_make_sample_files(4),
    )
    assert response.status_code == 422
    assert "at least 5 sample files" in response.text

    # More than 10 files
    response = client.post(
        f"/v1/admin/doc-types/{DOC_TYPE_ID}/prototype-upload",
        files=_make_sample_files(11),
    )
    assert response.status_code == 422
    assert "maximum 10 sample files" in response.text


def test_prototype_upload_rejects_malware(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.api.v1.admin.clamd_scan",
        lambda host, port, data: ScanVerdict(clean=False, signature="Eicar-Test-Signature"),
    )

    client = client_factory(user=make_user(**ADMIN))
    response = client.post(
        f"/v1/admin/doc-types/{DOC_TYPE_ID}/prototype-upload",
        files=_make_sample_files(5),
    )
    assert response.status_code == 422
    assert "Malware detected" in response.text
    assert "Eicar-Test-Signature" in response.text


def test_prototype_upload_success(client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock scanning clean
    monkeypatch.setattr(
        "app.api.v1.admin.clamd_scan",
        lambda host, port, data: ScanVerdict(clean=True, signature=None),
    )
    # Mock embedding
    monkeypatch.setattr(
        "app.api.v1.admin.embed_sample_text",
        lambda text: [1.0, 0.5, 0.25],
    )

    upsert_called: list[dict[str, Any]] = []

    async def fake_upsert(
        session: Any,
        *,
        tenant_id: UUID,
        doc_type_id: UUID,
        centroid: list[float],
        sample_count: int,
    ) -> None:
        upsert_called.append(
            {
                "tenant_id": tenant_id,
                "doc_type_id": doc_type_id,
                "centroid": centroid,
                "sample_count": sample_count,
            }
        )

    monkeypatch.setattr("app.api.v1.admin._upsert_prototype", fake_upsert)

    audit_calls: list[dict[str, Any]] = []

    async def fake_record_audit(
        session: Any,
        *,
        tenant_id: UUID,
        document_id: UUID | None,
        actor_id: UUID,
        action: str,
        request: Any,
        detail: str | None = None,
    ) -> None:
        audit_calls.append({"action": action, "detail": detail})

    monkeypatch.setattr("app.api.deps.record_audit", fake_record_audit)

    class DummyResult:
        def scalar_one_or_none(self) -> UUID:
            return DOC_TYPE_ID

    async def fake_execute(stmt: Any) -> DummyResult:
        return DummyResult()

    monkeypatch.setattr(SENTINEL_SESSION, "execute", fake_execute)

    client = client_factory(user=make_user(**ADMIN))
    response = client.post(
        f"/v1/admin/doc-types/{DOC_TYPE_ID}/prototype-upload",
        files=_make_sample_files(5),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["doc_type_id"] == str(DOC_TYPE_ID)
    assert data["sample_count"] == 5
    assert data["dimension"] == 3
    assert len(upsert_called) == 1
    assert upsert_called[0]["sample_count"] == 5
    assert len(audit_calls) == 1
    assert audit_calls[0]["action"] == "prototype.train"
    assert "source=direct_upload" in audit_calls[0]["detail"]


def test_reset_doc_type_prototype(client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    deleted_called: list[dict[str, Any]] = []

    async def fake_delete(session: Any, *, tenant_id: UUID, doc_type_id: UUID) -> int:
        deleted_called.append({"tenant_id": tenant_id, "doc_type_id": doc_type_id})
        return 1

    monkeypatch.setattr("app.api.v1.admin._delete_prototype", fake_delete)

    audit_calls: list[dict[str, Any]] = []

    async def fake_record_audit(
        session: Any,
        *,
        tenant_id: UUID,
        document_id: UUID | None,
        actor_id: UUID,
        action: str,
        request: Any,
        detail: str | None = None,
    ) -> None:
        audit_calls.append({"action": action, "detail": detail})

    monkeypatch.setattr("app.api.deps.record_audit", fake_record_audit)

    client = client_factory(user=make_user(**ADMIN))
    response = client.delete(f"/v1/admin/doc-types/{DOC_TYPE_ID}/prototype")
    assert response.status_code == 204
    assert len(deleted_called) == 1
    assert deleted_called[0]["doc_type_id"] == DOC_TYPE_ID
    assert len(audit_calls) == 1
    assert audit_calls[0]["action"] == "prototype.reset"


def test_reset_all_prototypes(client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    deleted_called: list[dict[str, Any]] = []

    async def fake_delete_all(session: Any, *, tenant_id: UUID) -> int:
        deleted_called.append({"tenant_id": tenant_id})
        return 3

    monkeypatch.setattr("app.api.v1.admin._delete_all_prototypes", fake_delete_all)

    audit_calls: list[dict[str, Any]] = []

    async def fake_record_audit(
        session: Any,
        *,
        tenant_id: UUID,
        document_id: UUID | None,
        actor_id: UUID,
        action: str,
        request: Any,
        detail: str | None = None,
    ) -> None:
        audit_calls.append({"action": action, "detail": detail})

    monkeypatch.setattr("app.api.deps.record_audit", fake_record_audit)

    client = client_factory(user=make_user(**ADMIN))
    response = client.delete("/v1/admin/prototypes")
    assert response.status_code == 204
    assert len(deleted_called) == 1
    assert len(audit_calls) == 1
    assert audit_calls[0]["action"] == "prototype.reset_all"
    assert "deleted_count=3" in audit_calls[0]["detail"]
