"""RFC 7807 envelope tests: every error path speaks application/problem+json.

The canonical 404 body is byte-stable across all document-not-found causes
(#31); these tests pin the envelope shape, the sanitised 500 and the
validation-error projection (no input values echoed — #31).
"""

from typing import Any

import pytest

from app.api.v1 import documents, uploads
from app.storage.base import BlobExistsError, ImmutableKeyError
from tests.api.conftest import install_worker_fake, make_user
from tests.api.test_uploads import drive_complete, seed_quarantine_and_complete

PROBLEM_TYPE = "application/problem+json"


def problem_of(response: Any) -> dict[str, Any]:
    assert response.headers["content-type"] == PROBLEM_TYPE
    return response.json()


def test_unknown_route_is_problem_json(client: Any) -> None:
    response = client.get("/v1/nope")
    body = problem_of(response)
    assert response.status_code == 404
    assert body["type"] == "about:blank"
    assert body["title"] == "Not Found"
    assert body["status"] == 404


def test_validation_error_is_400_problem_without_input_echo(client: Any) -> None:
    response = client.post("/v1/uploads", json={"filename": 123})
    body = problem_of(response)
    assert response.status_code == 400
    assert body["title"] == "Bad Request"
    assert isinstance(body.get("errors"), list) and body["errors"]
    assert all("input" not in entry for entry in body["errors"])


def test_missing_bearer_token_is_401_problem(raw_client: Any) -> None:
    response = raw_client.get("/v1/documents")
    body = problem_of(response)
    assert response.status_code == 401
    assert body["title"] == "Unauthorized"


def test_garbage_token_is_401_problem(raw_client: Any) -> None:
    response = raw_client.get("/v1/documents", headers={"Authorization": "Bearer not-a-jwt"})
    body = problem_of(response)
    assert response.status_code == 401
    assert body["title"] == "Unauthorized"


def test_wrong_secret_token_is_401(raw_client: Any) -> None:
    from tests.api.conftest import bearer_for

    token = bearer_for(secret="some-other-secret")  # noqa: S106 - synthetic
    response = raw_client.get("/v1/documents", headers={"Authorization": token})
    assert response.status_code == 401


def test_schemeless_header_rejected(raw_client: Any) -> None:
    response = raw_client.get("/v1/documents", headers={"Authorization": "Basic abc"})
    assert response.status_code == 401


def test_unexpected_exception_is_sanitised_500(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(session: Any, user: Any, after: Any, limit: Any) -> list[Any]:
        raise RuntimeError("secret internals: /etc/passwd")

    monkeypatch.setattr(documents, "_fetch_document_page", boom)
    client = client_factory(user=make_user(), raise_server_exceptions=False)
    response = client.get("/v1/documents")
    body = problem_of(response)
    assert response.status_code == 500
    assert body["detail"] == "internal error"
    assert "passwd" not in response.text


def test_unknown_mime_maps_to_422(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    blob_storage: Any,
    journal: list[dict[str, Any]],
) -> None:
    install_worker_fake(monkeypatch)
    response, _ = seed_quarantine_and_complete(
        client_factory,
        monkeypatch,
        blob_storage,
        filename="blob.bin",
        payload=b"\x00\x01\x02not-a-known-signature",
    )
    body = problem_of(response)
    assert response.status_code == 422
    assert body["title"] == "Unprocessable Entity"


@pytest.mark.parametrize("error_cls", [BlobExistsError, ImmutableKeyError])
def test_storage_conflicts_map_to_409(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    error_cls: type[Exception],
) -> None:
    def raiser(
        storage: Any,
        key: str,
        *,
        declared_size: int | None,
        max_bytes: int,
        tenant_id: Any,
    ) -> Any:
        raise error_cls(key)

    monkeypatch.setattr(uploads, "_ingest_bytes", raiser)
    client = client_factory(user=make_user(role="employee"))
    response = drive_complete(client, monkeypatch)
    body = problem_of(response)
    assert response.status_code == 409
    assert body["title"] == "Conflict"


def test_file_not_found_maps_to_canonical_404(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1.errors import not_found

    def raiser(
        storage: Any,
        key: str,
        *,
        declared_size: int | None,
        max_bytes: int,
        tenant_id: Any,
    ) -> Any:
        raise FileNotFoundError(key)

    monkeypatch.setattr(uploads, "_ingest_bytes", raiser)
    client = client_factory(user=make_user(role="employee"))
    response = drive_complete(client, monkeypatch)
    assert response.status_code == 404
    assert response.content == not_found().body
