"""Cross-tenant 404 indistinguishability (#31).

For every document-scoped endpoint: a foreign-tenant document, a
clearance-denied same-tenant document and a nonexistent uuid must produce
BYTE-IDENTICAL canonical 404 bodies. No presign may be issued and no audit
row written on any denial path (#17).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.api.v1.documents import DocumentView, ReclassifyContext
from app.storage.keys import primary_key
from tests.api.conftest import TENANT_A, TENANT_B, make_user

DOC_ID = UUID(int=0xD0C)
VERSION_ID = UUID(int=0x7E5710)
SHA = "cd" * 32


def view_for(tenant_id: UUID, *, level_rank: int) -> DocumentView:
    return DocumentView(
        id=DOC_ID,
        tenant_id=tenant_id,
        department_id=None,
        level_rank=level_rank,
        deleted_at=None,
        status="ready",
        original_filename="secret.pdf",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        level_name="restricted" if level_rank >= 4 else "internal",
        doc_type_name=None,
        blob_key=primary_key(TENANT_A, SHA),
        blob_mime="application/pdf",
        blob_size=10,
        current_version_id=VERSION_ID,
    )


def install_view(monkeypatch: pytest.MonkeyPatch, view: DocumentView | None) -> None:
    async def loader(session: Any, document_id: UUID) -> DocumentView | None:
        return view

    monkeypatch.setattr("app.api.v1.documents._fetch_document_view", loader)


def install_reclassify_loader(monkeypatch: pytest.MonkeyPatch, context: Any) -> None:
    async def loader(session: Any, document_id: UUID) -> Any:
        return context

    monkeypatch.setattr("app.api.v1.documents._load_reclassify_context", loader)


FOREIGN_ADMIN = make_user(tenant_id=TENANT_B, clearance_rank=4, role="security_officer")
LOW_CLEARANCE = make_user(tenant_id=TENANT_A, clearance_rank=1, role="security_officer")

DENIAL_USERS = ["foreign_tenant", "low_clearance", "nonexistent"]


def client_for(client_factory: Any, scenario: str) -> Any:
    if scenario == "foreign_tenant":
        return client_factory(user=FOREIGN_ADMIN)
    if scenario == "low_clearance":
        return client_factory(user=LOW_CLEARANCE)
    return client_factory(
        user=make_user(tenant_id=TENANT_A, clearance_rank=4, role="security_officer")
    )


def assert_all_denials_byte_identical(
    responses: dict[str, Any],
) -> None:
    bodies = [response.content for response in responses.values()]
    for response in responses.values():
        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"
    assert len(set(bodies)) == 1, "denial bodies must be byte-identical (#31)"


@pytest.fixture
def denial_views(monkeypatch: pytest.MonkeyPatch) -> dict[str, DocumentView | None]:
    return {
        "foreign_tenant": view_for(TENANT_A, level_rank=2),
        "low_clearance": view_for(TENANT_A, level_rank=4),
        "nonexistent": None,
    }


@pytest.mark.parametrize("scenario", DENIAL_USERS)
def test_detail_404_identical(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    denial_views: dict[str, Any],
    scenario: str,
) -> None:
    install_view(monkeypatch, denial_views[scenario])
    client = client_for(client_factory, scenario)
    responses = {"this": client.get(f"/v1/documents/{DOC_ID}")}
    assert_all_denials_byte_identical(responses)


def test_detail_all_scenarios_agree(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch, denial_views: dict[str, Any]
) -> None:
    responses: dict[str, Any] = {}
    for scenario in DENIAL_USERS:
        install_view(monkeypatch, denial_views[scenario])
        responses[scenario] = client_for(client_factory, scenario).get(f"/v1/documents/{DOC_ID}")
    assert_all_denials_byte_identical(responses)


def test_content_all_scenarios_agree_no_presign_no_audit(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    denial_views: dict[str, Any],
    journal: list[dict[str, Any]],
) -> None:
    responses: dict[str, Any] = {}
    for scenario in DENIAL_USERS:
        install_view(monkeypatch, denial_views[scenario])
        responses[scenario] = client_for(client_factory, scenario).get(
            f"/v1/documents/{DOC_ID}/content", follow_redirects=False
        )
    assert_all_denials_byte_identical(responses)
    # #17: no presigned URL may leak on a denied path; #30: no audit either.
    for response in responses.values():
        assert "location" not in response.headers
    assert journal == []


def test_findings_all_scenarios_agree(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch, denial_views: dict[str, Any]
) -> None:
    responses: dict[str, Any] = {}
    for scenario in DENIAL_USERS:
        install_view(monkeypatch, denial_views[scenario])
        responses[scenario] = client_for(client_factory, scenario).get(
            f"/v1/documents/{DOC_ID}/findings"
        )
    assert_all_denials_byte_identical(responses)


def test_jobs_all_scenarios_agree(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch, denial_views: dict[str, Any]
) -> None:
    responses: dict[str, Any] = {}
    for scenario in DENIAL_USERS:
        install_view(monkeypatch, denial_views[scenario])
        responses[scenario] = client_for(client_factory, scenario).get(
            f"/v1/documents/{DOC_ID}/jobs"
        )
    assert_all_denials_byte_identical(responses)


def test_reclassify_all_scenarios_agree_no_audit(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    denial_views: dict[str, Any],
    journal: list[dict[str, Any]],
) -> None:
    responses: dict[str, Any] = {}
    for scenario in DENIAL_USERS:
        context = (
            None
            if denial_views[scenario] is None
            else ReclassifyContext(view=denial_views[scenario], current_version_id=VERSION_ID)
        )
        install_reclassify_loader(monkeypatch, context)
        responses[scenario] = client_for(client_factory, scenario).post(
            f"/v1/documents/{DOC_ID}/classification",
            json={"level_name": "confidential"},
        )
    assert_all_denials_byte_identical(responses)
    assert journal == []
