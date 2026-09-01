"""Upload intent + completion tests.

Real code under test: size-cap gating, audit actions, broker-failure semantics.
Persistence and enqueue seams are fakes per the conftest strategy.
"""

import io
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.api.v1 import uploads
from app.storage.keys import quarantine_key
from tests.api.conftest import (
    ACTOR_ID,
    SENTINEL_SESSION,
    TENANT_A,
    install_worker_fake,
    make_user,
)

#: A stand-in tenant root. The real value comes from the database;
#: these tests only need the department seam to be non-empty.
DEPT_ROOT = UUID(int=0xD000)

DOC_ID = UUID(int=0xC0FFEE)
VERSION_ID = UUID(int=0x7E5710)
PDF_BYTES = b"%PDF-1.4\nminimal pdf payload\n"


def patch_intent_persistence(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
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
        captured["department_ids"] = department_ids
        captured["document_id"] = document_id
        captured["filename"] = filename
        captured["actor_id"] = actor_id

    async def resolve_departments(session: Any, user: Any, requested: Any) -> set[UUID]:
        # The department lookup is a real SELECT; these tests run on a fake
        # session. What it returns is asserted in tests/api/test_document_departments.py.
        captured["requested_departments"] = requested
        return {DEPT_ROOT}

    monkeypatch.setattr(uploads, "_provision_actor", provision)
    monkeypatch.setattr(uploads, "_insert_quarantine_document", insert_doc)
    monkeypatch.setattr(uploads, "_resolve_departments", resolve_departments)


def patch_complete_persistence(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
    async def load(session: Any, upload_id: UUID) -> Any:
        return uploads.QuarantinedDoc(
            id=upload_id,
            tenant_id=TENANT_A,
            department_id=None,
            original_filename="whatever.pdf",
            status=captured.get("status", "quarantined"),
            deleted_at=None,
        )

    async def persist(
        session: Any,
        *,
        document_id: UUID,
        actor_id: UUID,
    ) -> UUID:
        captured["persist_session"] = session
        return VERSION_ID

    async def provision(session: Any, user: Any) -> UUID:
        return ACTOR_ID

    monkeypatch.setattr(uploads, "_load_quarantined", load)
    monkeypatch.setattr(uploads, "_persist_version", persist)
    monkeypatch.setattr(uploads, "_provision_actor", provision)


def post_intent(client: Any, *, filename: str, size_bytes: int) -> Any:
    return client.post(
        "/v1/uploads",
        json={
            "filename": filename,
            "size_bytes": size_bytes,
            "content_type": "application/pdf",
        },
    )


def drive_complete(client: Any, monkeypatch: pytest.MonkeyPatch, **load_overrides: Any) -> Any:
    """Run a complete() against fakes only (ingest behaviour supplied by caller)."""
    captured: dict[str, Any] = {}
    patch_complete_persistence(monkeypatch, captured)
    captured.update(load_overrides)
    install_worker_fake(monkeypatch)
    return client.post(f"/v1/uploads/{DOC_ID}/complete")


def seed_quarantine_and_complete(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    blob_storage: Any,
    *,
    filename: str,
    payload: bytes,
    declared_size: int | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Full intent -> seed quarantine bytes -> complete with REAL ingest."""
    captured: dict[str, Any] = {}
    patch_intent_persistence(monkeypatch, captured)
    patch_complete_persistence(monkeypatch, captured)

    client = client_factory(user=make_user(role="employee"))
    intent = post_intent(client, filename=filename, size_bytes=declared_size or len(payload))
    assert intent.status_code == 201, intent.text
    document_id = captured["document_id"]
    blob_storage.put(
        quarantine_key(TENANT_A, document_id),
        io.BytesIO(payload),
        content_type="application/octet-stream",
    )
    response = client.post(
        f"/v1/uploads/{document_id}/complete", json={"size_bytes": declared_size}
    )
    return response, captured


def test_intent_creates_quarantined_document_and_audits(
    client: Any, monkeypatch: pytest.MonkeyPatch, journal: list[dict[str, Any]]
) -> None:
    captured: dict[str, Any] = {}
    patch_intent_persistence(monkeypatch, captured)
    response = post_intent(client, filename="contract.pdf", size_bytes=1234)
    body = response.json()
    assert response.status_code == 201
    assert body["upload_id"] == str(captured["document_id"])
    assert body["presigned_put"]["url"]
    expires = datetime.fromisoformat(body["presigned_put"]["expires_at"])
    assert 0 < (expires - datetime.now(tz=UTC)).total_seconds() <= 900
    assert captured["filename"] == "contract.pdf"
    assert len(journal) == 1
    entry = journal[0]
    assert entry["action"] == "upload.init"
    assert entry["session"] is SENTINEL_SESSION
    assert entry["document_id"] == captured["document_id"]
    assert entry["actor_id"] == ACTOR_ID


def test_intent_over_cap_is_413_without_insert_or_audit(
    client: Any, monkeypatch: pytest.MonkeyPatch, journal: list[dict[str, Any]]
) -> None:
    captured: dict[str, Any] = {}
    patch_intent_persistence(monkeypatch, captured)
    response = post_intent(client, filename="big.pdf", size_bytes=2_000_000)
    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert "document_id" not in captured
    assert journal == []


def test_viewer_role_cannot_upload(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch, journal: list[dict[str, Any]]
) -> None:
    captured: dict[str, Any] = {}
    patch_intent_persistence(monkeypatch, captured)
    client = client_factory(user=make_user(role="viewer"))
    response = post_intent(client, filename="x.pdf", size_bytes=10)
    assert response.status_code == 403
    assert journal == []


def test_upload_requires_token(raw_client: Any) -> None:
    assert raw_client.post("/v1/uploads", json={}).status_code == 401


def test_complete_happy_path(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    blob_storage: Any,
    journal: list[dict[str, Any]],
) -> None:
    install_worker_fake(monkeypatch)
    response, _captured = seed_quarantine_and_complete(
        client_factory,
        monkeypatch,
        blob_storage,
        filename="contract.pdf",
        payload=PDF_BYTES,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "processing"
    assert UUID(body["version_id"]) == VERSION_ID
    assert journal[-1]["action"] == "upload.complete"
    assert journal[-1]["session"] is SENTINEL_SESSION


def test_enqueue_receives_document_and_version(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    blob_storage: Any,
) -> None:
    calls = install_worker_fake(monkeypatch)
    response, captured = seed_quarantine_and_complete(
        client_factory,
        monkeypatch,
        blob_storage,
        filename="a.pdf",
        payload=PDF_BYTES,
    )
    assert response.status_code == 200
    document_id = str(captured["document_id"])
    assert calls == [(document_id, str(VERSION_ID))]


def test_broker_down_returns_503_but_state_committed(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    blob_storage: Any,
    journal: list[dict[str, Any]],
) -> None:
    captured: dict[str, Any] = {}
    patch_intent_persistence(monkeypatch, captured)
    patch_complete_persistence(monkeypatch, captured)
    install_worker_fake(monkeypatch, fail_delay=True)

    client = client_factory(user=make_user(role="employee"))
    assert post_intent(client, filename="a.pdf", size_bytes=len(PDF_BYTES)).status_code == 201
    document_id = captured["document_id"]
    blob_storage.put(
        quarantine_key(TENANT_A, document_id),
        io.BytesIO(PDF_BYTES),
        content_type="application/octet-stream",
    )
    response = client.post(f"/v1/uploads/{document_id}/complete")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    # persistence + audit happened BEFORE the enqueue attempt (same-tx commit)
    assert "persist_session" in captured
    assert journal[-1]["action"] == "upload.complete"


def test_missing_worker_chain_is_503(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    blob_storage: Any,
) -> None:
    captured: dict[str, Any] = {}
    patch_intent_persistence(monkeypatch, captured)
    patch_complete_persistence(monkeypatch, captured)

    def _failing_enqueue(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Worker unavailable")

    monkeypatch.setattr("app.api.v1.uploads._enqueue_chain", _failing_enqueue)

    client = client_factory(user=make_user(role="employee"))
    assert post_intent(client, filename="a.pdf", size_bytes=len(PDF_BYTES)).status_code == 201
    document_id = captured["document_id"]
    blob_storage.put(
        quarantine_key(TENANT_A, document_id),
        io.BytesIO(PDF_BYTES),
        content_type="application/octet-stream",
    )
    response = client.post(f"/v1/uploads/{document_id}/complete")
    assert response.status_code == 503


def test_complete_on_non_quarantined_is_409(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {"status": "processing"}
    patch_complete_persistence(monkeypatch, captured)
    install_worker_fake(monkeypatch)
    response = client.post(f"/v1/uploads/{DOC_ID}/complete")
    assert response.status_code == 409


def test_complete_unknown_document_is_canonical_404(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1.errors import not_found

    async def load(session: Any, upload_id: UUID) -> None:
        return None

    monkeypatch.setattr(uploads, "_load_quarantined", load)
    response = client.post(f"/v1/uploads/{DOC_ID}/complete")
    assert response.status_code == 404
    assert response.content == not_found().body
