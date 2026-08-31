"""Content split-path tests (#17): Confidential/Restricted stream through the
API with Range support; Public/Internal redirect to a clamped presigned URL.

Real code under test: Range parsing, 206/Content-Range construction, split
decision on level rank, presign TTL clamp, audit actions. The document view
loader is faked; storage is a real LocalStorage over tmp_path.
"""

import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from app.api.v1.documents import DocumentView
from app.storage.keys import primary_key
from tests.api.conftest import (
    SENTINEL_SESSION,
    TENANT_A,
    make_user,
)

DOC_ID = UUID(int=0xD0C)
VERSION_ID = UUID(int=0x7E5710)
SHA = "ab" * 32
PAYLOAD = b"0123456789"


def make_view(**overrides: Any) -> DocumentView:
    defaults: dict[str, Any] = {
        "id": DOC_ID,
        "tenant_id": TENANT_A,
        "department_id": None,
        "level_rank": 3,
        "deleted_at": None,
        "status": "ready",
        "original_filename": "report.pdf",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "level_name": "confidential",
        "doc_type_name": None,
        "blob_key": primary_key(TENANT_A, SHA),
        "blob_mime": "application/pdf",
        "blob_size": len(PAYLOAD),
        "current_version_id": VERSION_ID,
    }
    defaults.update(overrides)
    return DocumentView(**defaults)


def install_view(monkeypatch: pytest.MonkeyPatch, view: DocumentView | None) -> None:
    async def loader(session: Any, document_id: UUID) -> DocumentView | None:
        return view

    monkeypatch.setattr("app.api.v1.documents._fetch_document_view", loader)


@pytest.fixture
def seeded_blob(blob_storage: Any) -> Any:
    import io

    blob_storage.put(
        primary_key(TENANT_A, SHA), io.BytesIO(PAYLOAD), content_type="application/pdf"
    )
    return blob_storage


def test_confidential_streams_206_with_content_range(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    seeded_blob: Any,
    journal: list[dict[str, Any]],
) -> None:
    install_view(monkeypatch, make_view())
    client = client_factory(user=make_user(clearance_rank=4))
    response = client.get(
        f"/v1/documents/{DOC_ID}/content",
        headers={"Range": "bytes=2-5"},
        follow_redirects=False,
    )
    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == f"bytes 2-5/{len(PAYLOAD)}"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "application/pdf"
    assert [entry["action"] for entry in journal] == ["download.stream"]
    assert journal[0]["session"] is SENTINEL_SESSION


def test_full_download_is_200_with_length(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    seeded_blob: Any,
) -> None:
    install_view(monkeypatch, make_view())
    client = client_factory(user=make_user(clearance_rank=4))
    response = client.get(f"/v1/documents/{DOC_ID}/content", follow_redirects=False)
    assert response.status_code == 200
    assert response.content == PAYLOAD
    assert response.headers["content-length"] == str(len(PAYLOAD))


def test_range_end_clamps_to_object_size(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    seeded_blob: Any,
) -> None:
    install_view(monkeypatch, make_view())
    client = client_factory(user=make_user(clearance_rank=4))
    response = client.get(
        f"/v1/documents/{DOC_ID}/content",
        headers={"Range": "bytes=8-99"},
        follow_redirects=False,
    )
    assert response.status_code == 206
    assert response.content == b"89"
    assert response.headers["content-range"] == f"bytes 8-9/{len(PAYLOAD)}"


def test_range_start_beyond_size_is_416(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    seeded_blob: Any,
) -> None:
    install_view(monkeypatch, make_view())
    client = client_factory(user=make_user(clearance_rank=4))
    response = client.get(
        f"/v1/documents/{DOC_ID}/content",
        headers={"Range": "bytes=50-60"},
        follow_redirects=False,
    )
    assert response.status_code == 416


def test_public_document_redirects_to_presigned_url(
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    seeded_blob: Any,
    journal: list[dict[str, Any]],
) -> None:
    install_view(monkeypatch, make_view(level_rank=1, level_name="public"))
    response = client.get(f"/v1/documents/{DOC_ID}/content", follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    parsed = urlsplit(location)
    assert "/v1/dev-storage/" in parsed.path
    query = parse_qs(parsed.query)
    ttl = int(query["expires"][0]) - int(time.time())
    assert 60 <= ttl <= 120
    assert [entry["action"] for entry in journal] == ["download.presign"]


def test_range_header_ignored_on_presigned_path(
    client: Any, monkeypatch: pytest.MonkeyPatch, seeded_blob: Any
) -> None:
    """MinIO-native range via URL params is out of scope this phase (#17 note)."""
    install_view(monkeypatch, make_view(level_rank=1, level_name="public"))
    response = client.get(
        f"/v1/documents/{DOC_ID}/content",
        headers={"Range": "bytes=2-5"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_viewer_role_cannot_download(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    seeded_blob: Any,
    journal: list[dict[str, Any]],
) -> None:
    install_view(monkeypatch, make_view())
    client = client_factory(user=make_user(role="viewer"))
    response = client.get(f"/v1/documents/{DOC_ID}/content", follow_redirects=False)
    assert response.status_code == 403
    assert journal == []


def test_low_clearance_denied_as_canonical_404(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    seeded_blob: Any,
) -> None:
    from app.api.v1.errors import not_found

    install_view(monkeypatch, make_view())
    client = client_factory(user=make_user(clearance_rank=1))
    response = client.get(f"/v1/documents/{DOC_ID}/content", follow_redirects=False)
    assert response.status_code == 404
    assert response.content == not_found().body


def test_missing_blob_is_canonical_404(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1.errors import not_found

    install_view(monkeypatch, make_view(blob_key=None))
    response = client.get(f"/v1/documents/{DOC_ID}/content", follow_redirects=False)
    assert response.status_code == 404
    assert response.content == not_found().body


def test_deleted_document_is_canonical_404(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    seeded_blob: Any,
) -> None:
    from app.api.v1.errors import not_found

    install_view(monkeypatch, make_view(deleted_at=datetime(2026, 1, 2, tzinfo=UTC)))
    client = client_factory(user=make_user(clearance_rank=4))
    response = client.get(f"/v1/documents/{DOC_ID}/content", follow_redirects=False)
    assert response.status_code == 404
    assert response.content == not_found().body


# --- dev-only local storage verification endpoint (D8) ---


def _presign_path(storage: Any, key: str) -> str:
    url = storage.presign(key, ttl=90, filename="report.pdf")
    return urlsplit(url).path + "?" + urlsplit(url).query


def test_dev_storage_streams_with_valid_signature(client: Any, seeded_blob: Any) -> None:
    key = primary_key(TENANT_A, SHA)
    response = client.get(_presign_path(seeded_blob, key))
    assert response.status_code == 200
    assert response.content == PAYLOAD


def test_dev_storage_rejects_bad_signature(client: Any, seeded_blob: Any) -> None:
    key = primary_key(TENANT_A, SHA)
    path = _presign_path(seeded_blob, key)
    tampered = path.split("sig=")[0] + "sig=" + "0" * 64
    response = client.get(tampered)
    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"


def test_dev_storage_rejects_expired_signature(
    client: Any, monkeypatch: pytest.MonkeyPatch, seeded_blob: Any
) -> None:

    monkeypatch.setattr("app.api.v1.dev_storage._now", lambda: time.time() + 10_000)
    key = primary_key(TENANT_A, SHA)
    path = _presign_path(seeded_blob, key)
    assert path.startswith("/v1/dev-storage/")
    response = client.get(path)
    assert response.status_code == 403


def test_dev_storage_missing_object_is_canonical_404(client: Any, seeded_blob: Any) -> None:
    from app.api.v1.errors import not_found

    key = "docs-quarantine/missing/object"
    response = client.get(_presign_path(seeded_blob, key))
    assert response.status_code == 404
    assert response.content == not_found().body


def test_view_inline_streams_with_content_disposition(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    seeded_blob: Any,
) -> None:
    install_view(monkeypatch, make_view(level_rank=4, level_name="restricted"))
    client = client_factory(user=make_user(clearance_rank=4))
    response = client.get(f"/v1/documents/{DOC_ID}/view")
    assert response.status_code == 200
    assert response.content == PAYLOAD
    assert "inline" in response.headers["content-disposition"]


def test_preview_endpoint_returns_justification(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    seeded_blob: Any,
) -> None:
    install_view(monkeypatch, make_view(level_rank=2, level_name="internal"))

    async def fake_findings(session: Any, document_id: Any) -> list[Any]:
        return []

    async def fake_keywords(session: Any, document_id: Any) -> list[str]:
        return ["report", "finance"]

    monkeypatch.setattr("app.api.v1.documents._fetch_findings", fake_findings)
    monkeypatch.setattr("app.api.v1.documents._fetch_keywords", fake_keywords)

    client = client_factory(user=make_user(clearance_rank=2))
    response = client.get(f"/v1/documents/{DOC_ID}/preview")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(DOC_ID)
    assert data["justification"]["level"] == "internal"
    assert "Internal: Default floor" in data["justification"]["level_reason"]
    assert data["justification"]["keywords"] == ["report", "finance"]
