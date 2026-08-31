"""An authorised caller gets 409 for an unpromoted blob; everyone else gets 404.

#31 requires cross-tenant and nonexistent 404s to be byte-identical. It does not
require lying to a caller who can already see the row in their own list.
"""

from __future__ import annotations

from starlette.status import HTTP_404_NOT_FOUND, HTTP_409_CONFLICT

ROUTES = ("content", "view")


def test_authorised_caller_gets_409_while_processing(client_factory, monkeypatch) -> None:  # noqa: ANN001
    client, doc_id = client_factory.with_document(blob_key=None, status="processing")
    for route in ROUTES:
        response = client.get(f"/v1/documents/{doc_id}/{route}")
        assert response.status_code == HTTP_409_CONFLICT, route
        assert response.json()["detail"] == "document is still processing"


def test_held_document_reports_its_own_state(client_factory) -> None:  # noqa: ANN001
    client, doc_id = client_factory.with_document(blob_key=None, status="held")
    body = client.get(f"/v1/documents/{doc_id}/content").json()
    assert "held" in body["detail"]


def test_cross_tenant_404_is_byte_identical_to_nonexistent(client_factory) -> None:  # noqa: ANN001
    """#31 parity must survive this change."""
    import uuid
    from tests.api.conftest import make_user
    
    outsider = make_user(tenant_id=uuid.uuid4())
    client = client_factory(user=outsider)
    foreign = client_factory.foreign_document_id()
    a = client.get(f"/v1/documents/{foreign}/content")
    b = client.get(f"/v1/documents/{uuid.uuid4()}/content")
    assert a.status_code == b.status_code == HTTP_404_NOT_FOUND
    assert a.content == b.content
