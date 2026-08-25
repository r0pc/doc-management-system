"""Review queue listing tests.

Real code under test: role gating (RESOLVE_REVIEW), keyset windowing contract
(limit+1 probe, next_cursor derivation), cursor codec reuse from the documents
router, caller-ctx passthrough (visibility axes are applied inside the page
query; Wave 5 integration proves the SQL itself).
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.api.v1.review import ReviewQueueItem
from tests.api.conftest import make_user

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

OFFICER: dict[str, object] = {"role": "security_officer", "clearance_rank": 4}


def queue_item(index: int, created_at: datetime | None = None) -> ReviewQueueItem:
    return ReviewQueueItem(
        review_id=UUID(int=index),
        document_id=UUID(int=0xD000 + index),
        filename=f"doc-{index}.pdf",
        level="internal",
        doc_type=None,
        confidence=0.91,
        decided_by="rules",
        findings_count=2,
        created_at=created_at or (EPOCH + timedelta(minutes=index)),
    )


def install_queue_fake(
    monkeypatch: pytest.MonkeyPatch, rows: list[ReviewQueueItem]
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def page(
        session: Any,
        user: Any,
        after: tuple[datetime, UUID] | None,
        limit_plus_one: int,
    ) -> list[ReviewQueueItem]:
        captured["user"] = user
        captured["after"] = after
        captured["limit_plus_one"] = limit_plus_one
        ordered = sorted(rows, key=lambda r: (r.created_at, r.review_id))
        if after is not None:
            ordered = [r for r in ordered if (r.created_at, r.review_id) > after]
        return ordered[:limit_plus_one]

    monkeypatch.setattr("app.api.v1.review._fetch_review_page", page)
    return captured


def test_employee_cannot_list_queue(client_factory: Any) -> None:
    client = client_factory(user=make_user(role="employee"))
    assert client.get("/v1/review").status_code == 403


def test_officer_lists_pending_items(client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = install_queue_fake(monkeypatch, [queue_item(0), queue_item(1)])
    client = client_factory(user=make_user(**OFFICER))  # type: ignore[arg-type]
    response = client.get("/v1/review", params={"limit": 1})
    body = response.json()
    assert response.status_code == 200
    assert [item["review_id"] for item in body["items"]] == [str(UUID(int=0))]
    assert body["items"][0]["filename"] == "doc-0.pdf"
    assert body["items"][0]["level"] == "internal"
    assert body["next_cursor"]
    # The handler forwards the caller ctx; the query applies BOTH axes (#25).
    assert captured["user"].clearance_rank == 4


def test_visibility_axes_travel_with_caller(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = install_queue_fake(monkeypatch, [])
    dept = UUID(int=0xD001)
    client = client_factory(
        user=make_user(
            **OFFICER,  # type: ignore[arg-type]
            department_id=dept,
            visible_department_ids=(dept,),
        )
    )
    assert client.get("/v1/review").status_code == 200
    assert captured["user"].visible_department_ids == (dept,)
    assert captured["user"].tenant_id is not None


def test_cursor_roundtrip_feeds_decoded_keyset(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [queue_item(i) for i in range(3)]
    captured = install_queue_fake(monkeypatch, rows)
    client = client_factory(user=make_user(**OFFICER))  # type: ignore[arg-type]
    first = client.get("/v1/review", params={"limit": 2}).json()
    second = client.get("/v1/review", params={"limit": 2, "cursor": first["next_cursor"]})
    body = second.json()
    assert [item["review_id"] for item in body["items"]] == [str(UUID(int=2))]
    assert body["next_cursor"] is None
    anchor = rows[1]
    assert captured["after"] == (anchor.created_at, anchor.review_id)


def test_garbage_cursor_is_400_problem(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_queue_fake(monkeypatch, [])
    client = client_factory(user=make_user(**OFFICER))  # type: ignore[arg-type]
    response = client.get("/v1/review", params={"cursor": "junk"})
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"


def test_default_limit_probes_one_extra(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = install_queue_fake(monkeypatch, [])
    client = client_factory(user=make_user(**OFFICER))  # type: ignore[arg-type]
    assert client.get("/v1/review").status_code == 200
    assert captured["limit_plus_one"] == 51


def test_queue_requires_token(raw_client: Any) -> None:
    assert raw_client.get("/v1/review").status_code == 401
