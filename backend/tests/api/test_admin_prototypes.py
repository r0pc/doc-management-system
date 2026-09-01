"""Admin prototype training route tests."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from tests.api.conftest import make_user

DOC_TYPE_ID = UUID("00000000-0000-0000-0000-000000000001")
DOC_IDS = [UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 6)]

ADMIN: dict[str, object] = {"role": "admin", "clearance_rank": 4}
EMPLOYEE: dict[str, object] = {"role": "employee", "clearance_rank": 2}


def test_prototype_route_is_gated_by_manage_taxonomy(client_factory: Any) -> None:
    client = client_factory(user=make_user(**EMPLOYEE))
    response = client.post(
        f"/v1/admin/doc-types/{DOC_TYPE_ID}/prototype",
        json={"document_ids": [str(d) for d in DOC_IDS]},
    )
    assert response.status_code == 403


def test_prototype_route_validates_sample_count(client_factory: Any) -> None:
    client = client_factory(user=make_user(**ADMIN))
    # Fewer than 5
    response = client.post(
        f"/v1/admin/doc-types/{DOC_TYPE_ID}/prototype",
        json={"document_ids": [str(d) for d in DOC_IDS[:4]]},
    )
    assert response.status_code in (400, 422)

    # More than 10
    more_ids = [str(UUID(f"00000000-0000-0000-0000-0000000000{i:02d}")) for i in range(1, 12)]
    response = client.post(
        f"/v1/admin/doc-types/{DOC_TYPE_ID}/prototype",
        json={"document_ids": more_ids},
    )
    assert response.status_code in (400, 422)


def test_prototype_route_rejects_missing_embeddings(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_embeddings(
        session: Any, tenant_id: UUID, document_ids: list[UUID]
    ) -> list[list[float]]:
        # Only 4 returned out of 5
        return [[1.0, 0.0, 0.0]] * 4

    monkeypatch.setattr("app.api.v1.admin._fetch_sample_embeddings", fake_fetch_embeddings)

    client = client_factory(user=make_user(**ADMIN))
    response = client.post(
        f"/v1/admin/doc-types/{DOC_TYPE_ID}/prototype",
        json={"document_ids": [str(d) for d in DOC_IDS]},
    )
    assert response.status_code == 409
    assert "no stored embedding" in response.text


def test_prototype_route_trains_and_records_audit(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_fetch_embeddings(
        session: Any, tenant_id: UUID, document_ids: list[UUID]
    ) -> list[list[float]]:
        return [[3.0, 4.0]] * 5

    async def fake_upsert_prototype(
        session: Any,
        *,
        tenant_id: UUID,
        doc_type_id: UUID,
        centroid: list[float],
        sample_count: int,
    ) -> None:
        captured["centroid"] = centroid
        captured["sample_count"] = sample_count
        captured["doc_type_id"] = doc_type_id

    async def fake_record_audit(session: Any, **kwargs: Any) -> None:
        captured["audit_action"] = kwargs.get("action")

    monkeypatch.setattr("app.api.v1.admin._fetch_sample_embeddings", fake_fetch_embeddings)
    monkeypatch.setattr("app.api.v1.admin._upsert_prototype", fake_upsert_prototype)
    monkeypatch.setattr("app.api.deps.record_audit", fake_record_audit)

    client = client_factory(user=make_user(**ADMIN))
    response = client.post(
        f"/v1/admin/doc-types/{DOC_TYPE_ID}/prototype",
        json={"document_ids": [str(d) for d in DOC_IDS]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["doc_type_id"] == str(DOC_TYPE_ID)
    assert data["sample_count"] == 5
    assert data["dimension"] == 2
    assert "centroid" not in data
    assert "centroid_vector" not in data
    assert captured["audit_action"] == "prototype.train"
    assert captured["sample_count"] == 5
