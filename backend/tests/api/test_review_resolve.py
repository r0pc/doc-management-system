"""Review resolution tests (#2, #8, #20, #21, #30).

Real code under test: role gating (RESOLVE_REVIEW), canonical-404 parity for
missing/cross-tenant items, one-transaction orchestration (append-only
classification insert -> pointer move -> THIS item closed -> audit row) and
the decided_by='human' semantics shared with the documents reclassify path.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.api.v1.documents import DocumentView
from app.api.v1.errors import not_found
from app.api.v1.review import ReviewContext
from tests.api.conftest import (
    SENTINEL_SESSION,
    TENANT_A,
    TENANT_B,
    make_user,
)

ITEM_ID = UUID(int=0x8E7)
DOC_ID = UUID(int=0xD0C)
VERSION_ID = UUID(int=0x7E5710)
NEW_LEVEL_ID = UUID(int=0x1E7E1)
OLD_LEVEL_ID = UUID(int=0x01D)
DOCTYPE_ID = UUID(int=0x7A9E)
NEW_CLASSIFICATION_ID = UUID(int=0xC1A)
OLD_CLASSIFICATION_ID = UUID(int=0xB1D)

VALID_LEVELS = {"public", "internal", "confidential", "restricted"}

OFFICER: dict[str, object] = {"role": "security_officer", "clearance_rank": 4}


def make_view(tenant_id: UUID = TENANT_A, *, level_rank: int = 2) -> DocumentView:
    return DocumentView(
        id=DOC_ID,
        tenant_id=tenant_id,
        department_id=None,
        level_rank=level_rank,
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


def make_context(
    state: str = "pending", tenant_id: UUID = TENANT_A, *, level_rank: int = 2
) -> ReviewContext:
    return ReviewContext(
        review_id=ITEM_ID,
        review_state=state,
        view=make_view(tenant_id, level_rank=level_rank),
        version_id=VERSION_ID,
    )


def install_resolve_fakes(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any], context: ReviewContext | None
) -> dict[str, Any]:
    """Fake every seam the resolve handler touches; model an append-only store."""
    store: dict[str, Any] = {
        "classifications": [
            {"id": OLD_CLASSIFICATION_ID, "level_id": OLD_LEVEL_ID, "decided_by": "ml"}
        ],
        "closed_items": [],
    }

    async def loader(session: Any, item_id: UUID) -> ReviewContext | None:
        return context

    async def resolve_level(session: Any, name: str) -> UUID | None:
        captured["level_name"] = name
        return NEW_LEVEL_ID if name in VALID_LEVELS else None

    async def doc_type_exists(session: Any, doc_type_id: UUID) -> bool:
        return doc_type_id == DOCTYPE_ID

    async def apply(
        session: Any,
        *,
        document_id: UUID,
        version_id: UUID,
        level_id: UUID,
        doc_type_id: UUID | None,
    ) -> UUID:
        captured["apply_session"] = session
        captured["document_id"] = document_id
        captured["version_id"] = version_id
        captured["level_id"] = level_id
        captured["doc_type_id"] = doc_type_id
        store["classifications"].append(
            {"id": NEW_CLASSIFICATION_ID, "level_id": level_id, "decided_by": "human"}
        )
        return NEW_CLASSIFICATION_ID

    async def close_item(session: Any, item_id: UUID) -> int:
        captured["close_item_id"] = item_id
        store["closed_items"].append(item_id)
        return 1

    monkeypatch.setattr("app.api.v1.review._fetch_review_context", loader)
    monkeypatch.setattr("app.api.v1.review._resolve_level_id", resolve_level)
    monkeypatch.setattr("app.api.v1.review._doc_type_exists", doc_type_exists)
    monkeypatch.setattr("app.api.v1.review._apply_human_classification", apply)
    monkeypatch.setattr("app.api.v1.review._close_review_item", close_item)
    captured["store"] = store
    return store


def officer_client(client_factory: Any) -> Any:
    return client_factory(user=make_user(**OFFICER))  # type: ignore[arg-type]


def post_resolve(client: Any, **overrides: Any) -> Any:
    payload: dict[str, Any] = {
        "level_name": "confidential",
        "decision": "correct",
    }
    payload.update(overrides)
    return client.post(f"/v1/review/{ITEM_ID}/resolve", json=payload)


def test_resolve_happy_path_single_tx(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch, journal: list[dict[str, Any]]
) -> None:
    captured: dict[str, Any] = {}
    store = install_resolve_fakes(monkeypatch, captured, make_context())
    before = len(store["classifications"])

    response = post_resolve(officer_client(client_factory), doc_type_id=str(DOCTYPE_ID))
    body = response.json()

    assert response.status_code == 200, response.text
    # Response reflects the NEW label.
    assert body["document_id"] == str(DOC_ID)
    assert body["level"] == "confidential"
    assert body["doc_type_id"] == str(DOCTYPE_ID)
    assert body["decided_by"] == "human"
    # Append-only (#20): exactly ONE new row; the old row is intact.
    assert len(store["classifications"]) == before + 1
    old_row = store["classifications"][0]
    assert old_row["level_id"] == OLD_LEVEL_ID and old_row["decided_by"] == "ml"
    new_row = store["classifications"][1]
    assert new_row["decided_by"] == "human" and new_row["level_id"] == NEW_LEVEL_ID
    # Version-scoped insert (#21).
    assert captured["version_id"] == VERSION_ID
    # THIS review item closed — not a blanket close of all pending items.
    assert captured["close_item_id"] == ITEM_ID
    assert store["closed_items"] == [ITEM_ID]
    # One audit row, same session/transaction as the writes (#30).
    assert [entry["action"] for entry in journal] == ["reclassify.resolve.human"]
    assert journal[0]["session"] is SENTINEL_SESSION
    assert journal[0]["session"] is captured["apply_session"]
    assert journal[0]["document_id"] == DOC_ID


@pytest.mark.parametrize("decision", ["accept", "correct"])
def test_accept_and_correct_both_decide_human(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    journal: list[dict[str, Any]],
    decision: str,
) -> None:
    captured: dict[str, Any] = {}
    install_resolve_fakes(monkeypatch, captured, make_context())
    response = post_resolve(officer_client(client_factory), decision=decision)
    assert response.status_code == 200
    assert response.json()["decided_by"] == "human"
    assert [entry["action"] for entry in journal] == ["reclassify.resolve.human"]


def test_missing_and_cross_tenant_are_byte_identical_404(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch, journal: list[dict[str, Any]]
) -> None:
    responses: dict[str, Any] = {}
    scenarios: dict[str, ReviewContext | None] = {
        "nonexistent": None,
        "cross_tenant": make_context(tenant_id=TENANT_B),
        "clearance_denied": make_context(level_rank=5),
    }
    officer = make_user(**OFFICER)  # type: ignore[arg-type]
    for scenario, context in scenarios.items():
        captured: dict[str, Any] = {}
        install_resolve_fakes(monkeypatch, captured, context)
        responses[scenario] = client_factory(user=officer).post(
            f"/v1/review/{ITEM_ID}/resolve", json={"level_name": "internal", "decision": "accept"}
        )
    bodies = {response.content for response in responses.values()}
    assert len(bodies) == 1, "denial bodies must be byte-identical (#31)"
    for response in responses.values():
        assert response.status_code == 404
        assert response.content == not_found().body
    assert journal == []


def test_employee_cannot_resolve(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch, journal: list[dict[str, Any]]
) -> None:
    captured: dict[str, Any] = {}
    store = install_resolve_fakes(monkeypatch, captured, make_context())
    response = post_resolve(client_factory(user=make_user(role="employee")))
    assert response.status_code == 403
    assert journal == []
    assert len(store["classifications"]) == 1
    assert store["closed_items"] == []


def test_already_resolved_item_is_409(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch, journal: list[dict[str, Any]]
) -> None:
    captured: dict[str, Any] = {}
    store = install_resolve_fakes(monkeypatch, captured, make_context(state="resolved"))
    response = post_resolve(officer_client(client_factory))
    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert len(store["classifications"]) == 1
    assert journal == []


def test_unknown_level_is_400_problem_without_apply(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    install_resolve_fakes(monkeypatch, captured, make_context())
    response = post_resolve(officer_client(client_factory), level_name="topsecret")
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    assert "apply_session" not in captured


def test_unknown_doc_type_is_400_without_apply(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    install_resolve_fakes(monkeypatch, captured, make_context())
    response = post_resolve(officer_client(client_factory), doc_type_id=str(UUID(int=0xBAD)))
    assert response.status_code == 400
    assert "apply_session" not in captured
