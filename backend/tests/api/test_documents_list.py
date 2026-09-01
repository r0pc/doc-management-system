"""Cursor-paginated document list tests.

Real code under test: opaque cursor codec, keyset windowing contract
(limit+1 probe, next_cursor derivation), limit clamping. The SQL keyset
itself is a fake here; Wave 5 integration proves it against Postgres.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.api.v1.documents import DocumentListItem
from tests.api.conftest import make_user

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def item(index: int, created_at: datetime | None = None) -> DocumentListItem:
    return DocumentListItem(
        id=UUID(int=index),
        filename=f"doc-{index}.pdf",
        status="ready",
        level="internal",
        doc_type=None,
        created_at=created_at or (EPOCH + timedelta(minutes=index)),
    )


def install_page_fake(
    monkeypatch: pytest.MonkeyPatch, rows: list[DocumentListItem]
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def page(
        session: Any,
        user: Any,
        after: Any,
        limit_plus_one: int,
        **kwargs: Any,
    ) -> list[DocumentListItem]:
        captured["after"] = after
        captured["limit_plus_one"] = limit_plus_one
        ordered = sorted(rows, key=lambda d: (d.created_at, d.id))
        if after is not None:
            ordered = [
                d for d in ordered if (d.created_at, d.id) > (after.value, after.document_id)
            ]
        return ordered[:limit_plus_one]

    monkeypatch.setattr("app.api.v1.documents._fetch_document_page", page)
    return captured


def test_list_returns_items_and_opaque_cursor(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [item(0), item(1), item(2)]
    captured = install_page_fake(monkeypatch, rows)
    response = client.get("/v1/documents", params={"limit": 2})
    body = response.json()
    assert response.status_code == 200
    assert [entry["id"] for entry in body["items"]] == [
        str(UUID(int=0)),
        str(UUID(int=1)),
    ]
    assert body["items"][0]["filename"] == "doc-0.pdf"
    assert body["next_cursor"]
    assert captured["limit_plus_one"] == 3


def test_cursor_roundtrip_feeds_decoded_keyset(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [item(0), item(1), item(2)]
    captured = install_page_fake(monkeypatch, rows)
    first = client.get("/v1/documents", params={"limit": 2}).json()
    cursor = first["next_cursor"]

    second = client.get("/v1/documents", params={"limit": 2, "cursor": cursor})
    body = second.json()
    assert [entry["id"] for entry in body["items"]] == [str(UUID(int=2))]
    assert body["next_cursor"] is None
    anchor = rows[1]
    assert captured["after"].value == anchor.created_at
    assert captured["after"].document_id == anchor.id
    assert captured["after"].field == "created_at"
    assert captured["after"].direction == "asc"


def test_garbage_cursor_is_400_problem(client: Any) -> None:
    response = client.get("/v1/documents", params={"cursor": "not-a-cursor"})
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"


def test_limit_at_ceiling_probes_one_extra(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = install_page_fake(monkeypatch, [])
    response = client.get("/v1/documents", params={"limit": 200})
    assert response.status_code == 200
    assert captured["limit_plus_one"] == 201


def test_limit_above_ceiling_rejected(client: Any) -> None:
    response = client.get("/v1/documents", params={"limit": 500})
    assert response.status_code == 400


def test_default_limit_is_50_plus_probe(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = install_page_fake(monkeypatch, [])
    client.get("/v1/documents")
    assert captured["limit_plus_one"] == 51


def test_zero_limit_rejected_by_validation(client: Any) -> None:
    response = client.get("/v1/documents", params={"limit": 0})
    assert response.status_code == 400


def test_cursor_stability_with_interleaved_insert(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keyset anchoring: a newer row inserted between pages causes neither
    duplication nor skipping of already-established ordering."""
    rows = [item(i) for i in range(5)]
    install_page_fake(monkeypatch, rows)

    page1 = client.get("/v1/documents", params={"limit": 2}).json()
    rows.append(item(99, created_at=EPOCH + timedelta(hours=1)))
    cursor = page1["next_cursor"]
    page2 = client.get("/v1/documents", params={"limit": 2, "cursor": cursor}).json()
    page3 = client.get("/v1/documents", params={"limit": 2, "cursor": page2["next_cursor"]}).json()

    seen = [
        *(entry["id"] for entry in page1["items"]),
        *(entry["id"] for entry in page2["items"]),
        *(entry["id"] for entry in page3["items"]),
    ]
    originals = {str(UUID(int=i)) for i in range(5)}
    assert originals.issubset(set(seen))
    assert len(seen) == len(set(seen)), "no duplicates across pages"


def test_viewer_role_can_list(client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    install_page_fake(monkeypatch, [])
    client = client_factory(user=make_user(role="viewer"))
    assert client.get("/v1/documents").status_code == 200


def test_list_requires_token(raw_client: Any) -> None:
    assert raw_client.get("/v1/documents").status_code == 401
