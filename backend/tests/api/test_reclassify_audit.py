"""Human reclassification tests (#2, #8, #20, #21, #30).

Real code under test: role gating (RECLASSIFY), level-name validation,
one-transaction orchestration across classification insert, pointer update,
review-item closure and the audit write.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.api.v1.documents import DocumentView, ReclassifyContext
from tests.api.conftest import (
    SENTINEL_SESSION,
    TENANT_A,
    make_user,
)

DOC_ID = UUID(int=0xD0C)
VERSION_ID = UUID(int=0x7E5710)
LEVEL_ID = UUID(int=0x1E7E1)
DOCTYPE_ID = UUID(int=0x7A9E)
CLASSIFICATION_ID = UUID(int=0xC1A)


def make_view() -> DocumentView:
    return DocumentView(
        id=DOC_ID,
        tenant_id=TENANT_A,
        department_id=None,
        level_rank=2,
        deleted_at=None,
        status="ready",
        original_filename="report.pdf",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        level_name="internal",
        doc_type_name=None,
        blob_key=None,
        blob_mime=None,
        blob_size=None,
        current_version_id=VERSION_ID,
    )


def install_happy_fakes(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
    async def loader(session: Any, document_id: UUID) -> ReclassifyContext:
        return ReclassifyContext(view=make_view(), current_version_id=VERSION_ID)

    async def resolve_level(session: Any, name: str) -> UUID | None:
        captured["level_name"] = name
        return LEVEL_ID if name in {"public", "internal", "confidential", "restricted"} else None

    async def doc_type_exists(session: Any, doc_type_id: UUID) -> bool:
        captured["doc_type_checked"] = doc_type_id
        return doc_type_id == DOCTYPE_ID

    async def apply(
        session: Any,
        *,
        document_id: UUID,
        version_id: UUID,
        level_id: UUID,
        doc_type_id: UUID | None,
    ) -> UUID:
        captured.update(
            {
                "apply_session": session,
                "document_id": document_id,
                "version_id": version_id,
                "level_id": level_id,
                "doc_type_id": doc_type_id,
            }
        )
        return CLASSIFICATION_ID

    closed: list[UUID] = []

    async def close_reviews(session: Any, document_id: UUID) -> int:
        closed.append(document_id)
        return 1

    monkeypatch.setattr("app.api.v1.documents._load_reclassify_context", loader)
    monkeypatch.setattr("app.api.v1.documents._resolve_level_id", resolve_level)
    monkeypatch.setattr("app.api.v1.documents._doc_type_exists", doc_type_exists)
    monkeypatch.setattr("app.api.v1.documents._apply_human_classification", apply)
    monkeypatch.setattr("app.api.v1.documents._close_pending_reviews", close_reviews)
    captured["closed"] = closed


OFFICER: dict[str, object] = {"role": "security_officer", "clearance_rank": 4}


def officer_client(client_factory: Any) -> Any:
    return client_factory(user=make_user(**OFFICER))


def post_reclassify(client: Any, **overrides: Any) -> Any:
    payload: dict[str, Any] = {"level_name": "confidential"}
    payload.update(overrides)
    return client.post(f"/v1/documents/{DOC_ID}/classification", json=payload)


def test_reclassify_happy_path_single_tx(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch, journal: list[dict[str, Any]]
) -> None:
    captured: dict[str, Any] = {}
    install_happy_fakes(monkeypatch, captured)
    response = post_reclassify(officer_client(client_factory), doc_type_id=str(DOCTYPE_ID))
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["level"] == "confidential"
    assert body["decided_by"] == "human"
    # #21: classification is version-scoped, not just document-scoped
    assert captured["version_id"] == VERSION_ID
    assert captured["level_id"] == LEVEL_ID
    assert captured["doc_type_id"] == DOCTYPE_ID
    assert captured["closed"] == [DOC_ID]
    # #30: audit rides the same session/transaction as the label writes
    assert [entry["action"] for entry in journal] == ["reclassify.human"]
    assert journal[0]["session"] is SENTINEL_SESSION
    assert journal[0]["session"] is captured["apply_session"]


def test_employee_cannot_reclassify(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch, journal: list[dict[str, Any]]
) -> None:
    captured: dict[str, Any] = {}
    install_happy_fakes(monkeypatch, captured)
    client = client_factory(user=make_user(role="employee"))
    response = post_reclassify(client)
    assert response.status_code == 403
    assert journal == []
    assert "apply_session" not in captured


def test_unknown_level_name_is_400_problem(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    install_happy_fakes(monkeypatch, captured)
    response = post_reclassify(officer_client(client_factory), level_name="topsecret")
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"


def test_unknown_doc_type_is_400_without_apply(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    install_happy_fakes(monkeypatch, captured)
    response = post_reclassify(officer_client(client_factory), doc_type_id=str(UUID(int=0xBAD)))
    assert response.status_code == 400
    assert "apply_session" not in captured


def test_reclassify_unknown_document_is_canonical_404(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1.errors import not_found

    async def loader(session: Any, document_id: UUID) -> None:
        return None

    monkeypatch.setattr("app.api.v1.documents._load_reclassify_context", loader)
    response = post_reclassify(officer_client(client_factory))
    assert response.status_code == 404
    assert response.content == not_found().body
