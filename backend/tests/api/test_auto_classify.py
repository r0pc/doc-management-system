"""Auto-classify documents in bulk, gated to Action.RECLASSIFY (admin and security_officer).

Re-evaluates documents through the automated classification pipeline.
Invariant #2: Workers are the automated classifier writer; request handler enqueues.
Invariant #8: Security level never decreases automatically.
Invariant #30: Audit rows share the transaction with the action.
Invariant #31: Cross-tenant 404/omission parity; foreign or denied IDs are silently omitted.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.api.v1 import documents as documents_module

AUTO_CLASSIFY_PATH = "/v1/documents/auto-classify"
DOC_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
VER_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DOC_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
VER_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
FOREIGN = uuid.UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture
def reclassified_mock(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Records what the route actually marked processing and enqueued."""
    state: dict[str, list[Any]] = {"marked": [], "enqueued": []}

    async def fake_eligible(
        session: Any, user: Any, document_ids: list[uuid.UUID]
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        valid = {DOC_A: VER_A, DOC_B: VER_B}
        return [(d, valid[d]) for d in document_ids if d in valid]

    async def fake_mark_processing(session: Any, document_ids: list[uuid.UUID]) -> None:
        state["marked"].extend(document_ids)

    def fake_enqueue(document_id: uuid.UUID, version_id: uuid.UUID) -> None:
        state["enqueued"].append((document_id, version_id))

    monkeypatch.setattr(documents_module, "_fetch_reclassifiable_documents", fake_eligible)
    monkeypatch.setattr(documents_module, "_mark_documents_processing", fake_mark_processing)
    monkeypatch.setattr(documents_module, "_enqueue_reclassify", fake_enqueue)
    return state


def test_admin_can_auto_classify_documents(
    client_factory: Any, reclassified_mock: dict[str, list[Any]]
) -> None:
    client = client_factory(role="admin")
    response = client.post(AUTO_CLASSIFY_PATH, json={"document_ids": [str(DOC_A), str(DOC_B)]})
    assert response.status_code == 200
    assert response.json()["reclassified"] == [str(DOC_A), str(DOC_B)]
    assert reclassified_mock["marked"] == [DOC_A, DOC_B]
    assert reclassified_mock["enqueued"] == [(DOC_A, VER_A), (DOC_B, VER_B)]


def test_security_officer_can_auto_classify(
    client_factory: Any, reclassified_mock: dict[str, list[Any]]
) -> None:
    client = client_factory(role="security_officer")
    response = client.post(AUTO_CLASSIFY_PATH, json={"document_ids": [str(DOC_A)]})
    assert response.status_code == 200
    assert response.json()["reclassified"] == [str(DOC_A)]
    assert reclassified_mock["marked"] == [DOC_A]
    assert reclassified_mock["enqueued"] == [(DOC_A, VER_A)]


@pytest.mark.parametrize("role", ["employee", "dept_manager", "viewer"])
def test_lower_roles_are_refused(
    client_factory: Any, reclassified_mock: dict[str, list[Any]], role: str
) -> None:
    """Action.RECLASSIFY is gated to admin and security_officer only."""
    client = client_factory(role=role)
    response = client.post(AUTO_CLASSIFY_PATH, json={"document_ids": [str(DOC_A)]})
    assert response.status_code == 403
    assert reclassified_mock["marked"] == []
    assert reclassified_mock["enqueued"] == []


def test_foreign_and_unknown_ids_are_omitted_without_leakage(
    client_factory: Any, reclassified_mock: dict[str, list[Any]]
) -> None:
    """#31: Never reveal whether an id was foreign, missing, or denied."""
    ghost = uuid.uuid4()
    client = client_factory(role="admin")
    body = client.post(
        AUTO_CLASSIFY_PATH, json={"document_ids": [str(DOC_A), str(FOREIGN), str(ghost)]}
    ).json()
    assert body["reclassified"] == [str(DOC_A)]
    assert str(ghost) not in str(body)
    assert str(FOREIGN) not in str(body)
    for key in ("denied", "not_found", "missing", "errors", "failed"):
        assert key not in body, f"{key} leaks why an id was skipped (#31)"


def test_auto_classify_writes_audit_row_per_document(
    client_factory: Any, reclassified_mock: dict[str, list[Any]], journal: list[dict[str, Any]]
) -> None:
    """#30: The audit write shares the transaction with the state update."""
    client = client_factory(role="admin")
    client.post(AUTO_CLASSIFY_PATH, json={"document_ids": [str(DOC_A), str(DOC_B)]})
    rows = [e for e in journal if e["action"] == "reclassify.auto"]
    assert len(rows) == 2
    assert {r["document_id"] for r in rows} == {DOC_A, DOC_B}


def test_nothing_reclassified_writes_no_audit_row(
    client_factory: Any, reclassified_mock: dict[str, list[Any]], journal: list[dict[str, Any]]
) -> None:
    client = client_factory(role="admin")
    client.post(AUTO_CLASSIFY_PATH, json={"document_ids": [str(FOREIGN)]})
    assert [e for e in journal if e["action"] == "reclassify.auto"] == []


def test_empty_selection_is_rejected(
    client_factory: Any, reclassified_mock: dict[str, list[Any]]
) -> None:
    client = client_factory(role="admin")
    assert client.post(AUTO_CLASSIFY_PATH, json={"document_ids": []}).status_code == 400


def test_oversized_selection_is_rejected(
    client_factory: Any, reclassified_mock: dict[str, list[Any]]
) -> None:
    client = client_factory(role="admin")
    ids = [str(uuid.uuid4()) for _ in range(501)]
    assert client.post(AUTO_CLASSIFY_PATH, json={"document_ids": ids}).status_code == 400


def test_duplicate_ids_are_processed_once(
    client_factory: Any, reclassified_mock: dict[str, list[Any]]
) -> None:
    client = client_factory(role="admin")
    body = client.post(AUTO_CLASSIFY_PATH, json={"document_ids": [str(DOC_A), str(DOC_A)]}).json()
    assert body["reclassified"] == [str(DOC_A)]
    assert reclassified_mock["marked"] == [DOC_A]
    assert reclassified_mock["enqueued"] == [(DOC_A, VER_A)]
