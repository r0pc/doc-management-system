"""Surface an existing document with identical content.

The API cannot hash at completion (#1 keeps it off the bytes), so the duplicate
is reported on the document detail route once the worker has promoted the blob.
"""

from __future__ import annotations

import uuid


def test_detail_reports_a_sibling_with_the_same_content(client_factory, monkeypatch) -> None:
    from app.api.v1 import documents

    sibling = uuid.uuid4()

    async def _mock_siblings(*a, **k):
        return [sibling]

    monkeypatch.setattr(documents, "_fetch_content_siblings", _mock_siblings)
    client, doc_id = client_factory.with_ready_document()
    body = client.get(f"/v1/documents/{doc_id}").json()
    assert body.get("duplicate_of") == [str(sibling)]


def test_detail_reports_no_duplicates_for_unique_content(client_factory, monkeypatch) -> None:
    from app.api.v1 import documents

    async def _mock_empty(*a, **k):
        return []

    monkeypatch.setattr(documents, "_fetch_content_siblings", _mock_empty)
    client, doc_id = client_factory.with_ready_document()
    assert client.get(f"/v1/documents/{doc_id}").json().get("duplicate_of") == []
