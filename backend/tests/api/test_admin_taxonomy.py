"""Taxonomy admin CRUD tests.

Real code under test: role gating (MANAGE_TAXONOMY), duplicate-name conflict
(409 problem), delete guards (children / classification references -> honest
409 strings), same-transaction audit actions and the READ-ONLY security-levels
surface (policy table owned outside engineering; no mutating routes).
"""

from typing import Any
from uuid import UUID

import pytest

from app.api.v1.admin import DocTypeOut, SecurityLevelOut
from tests.api.conftest import SENTINEL_SESSION, make_user

PARENT_ID = UUID(int=0x0DD)
NEW_TYPE_ID = UUID(int=0x7A9E)
TARGET_ID = UUID(int=0x8AD)

ADMIN: dict[str, object] = {"role": "admin", "clearance_rank": 4}


def admin_client(client_factory: Any) -> Any:
    return client_factory(user=make_user(**ADMIN))  # type: ignore[arg-type]


def install_admin_fakes(
    monkeypatch: pytest.MonkeyPatch,
    captured: dict[str, Any],
    *,
    name_conflict: bool = False,
    children: int = 0,
    references: int = 0,
) -> None:
    async def list_types(session: Any) -> list[DocTypeOut]:
        return [DocTypeOut(id=PARENT_ID, parent_id=None, name="Contract", description="")]

    async def name_conflicts(session: Any, name: str, parent_id: UUID | None) -> bool:
        captured["conflict_name"] = name
        captured["conflict_parent"] = parent_id
        return name_conflict

    async def insert_type(
        session: Any, *, name: str, parent_id: UUID | None, description: str
    ) -> UUID:
        captured["insert_session"] = session
        captured["insert_name"] = name
        captured["insert_parent"] = parent_id
        captured["insert_description"] = description
        return NEW_TYPE_ID

    async def count_children(session: Any, doc_type_id: UUID) -> int:
        captured["children_of"] = doc_type_id
        return children

    async def count_references(session: Any, doc_type_id: UUID) -> int:
        captured["references_of"] = doc_type_id
        return references

    async def delete_type(session: Any, doc_type_id: UUID) -> None:
        captured["deleted"] = doc_type_id

    async def list_levels(session: Any) -> list[SecurityLevelOut]:
        return [SecurityLevelOut(id=UUID(int=0x1E7E1), rank=2, name="internal", description="d")]

    monkeypatch.setattr("app.api.v1.admin._fetch_doc_types", list_types)
    monkeypatch.setattr("app.api.v1.admin._doc_type_name_conflicts", name_conflicts)
    monkeypatch.setattr("app.api.v1.admin._insert_doc_type", insert_type)
    monkeypatch.setattr("app.api.v1.admin._count_doc_type_children", count_children)
    monkeypatch.setattr("app.api.v1.admin._count_classification_refs", count_references)
    monkeypatch.setattr("app.api.v1.admin._delete_doc_type", delete_type)
    monkeypatch.setattr("app.api.v1.admin._fetch_security_levels", list_levels)


def test_viewer_cannot_read_taxonomy(client_factory: Any) -> None:
    client = client_factory(user=make_user(role="viewer"))
    assert client.get("/v1/admin/doc-types").status_code == 403


def test_employee_cannot_create_doc_type(client_factory: Any) -> None:
    client = client_factory(user=make_user(role="employee"))
    response = client.post("/v1/admin/doc-types", json={"name": "Contract"})
    assert response.status_code == 403


def test_create_doc_type_happy_path_audits_same_tx(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    journal: list[dict[str, Any]],
) -> None:
    captured: dict[str, Any] = {}
    install_admin_fakes(monkeypatch, captured)
    response = admin_client(client_factory).post(
        "/v1/admin/doc-types",
        json={"name": "Vendor MSA", "parent_id": str(PARENT_ID)},
    )
    body = response.json()
    assert response.status_code == 201, response.text
    assert body["id"] == str(NEW_TYPE_ID)
    assert body["name"] == "Vendor MSA"
    assert body["parent_id"] == str(PARENT_ID)
    assert captured["insert_parent"] == PARENT_ID
    # Same-transaction audit (#30).
    assert [entry["action"] for entry in journal] == ["taxonomy.create"]
    assert journal[0]["session"] is SENTINEL_SESSION


def test_duplicate_name_is_409_problem_no_insert_no_audit(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    journal: list[dict[str, Any]],
) -> None:
    captured: dict[str, Any] = {}
    install_admin_fakes(monkeypatch, captured, name_conflict=True)
    response = admin_client(client_factory).post("/v1/admin/doc-types", json={"name": "Contract"})
    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert "insert_session" not in captured
    assert journal == []


def test_delete_with_children_is_409(client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    install_admin_fakes(monkeypatch, captured, children=2)
    response = admin_client(client_factory).delete(f"/v1/admin/doc-types/{TARGET_ID}")
    assert response.status_code == 409
    assert "child" in response.json()["detail"]
    assert "deleted" not in captured


def test_delete_referenced_by_classifications_is_409(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    install_admin_fakes(monkeypatch, captured, references=5)
    response = admin_client(client_factory).delete(f"/v1/admin/doc-types/{TARGET_ID}")
    assert response.status_code == 409
    assert "classification" in response.json()["detail"]
    assert "deleted" not in captured


def test_delete_happy_path_audits_same_tx(
    client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    journal: list[dict[str, Any]],
) -> None:
    captured: dict[str, Any] = {}
    install_admin_fakes(monkeypatch, captured)
    response = admin_client(client_factory).delete(f"/v1/admin/doc-types/{TARGET_ID}")
    assert response.status_code == 204
    assert captured["deleted"] == TARGET_ID
    assert [entry["action"] for entry in journal] == ["taxonomy.delete"]
    assert journal[0]["session"] is SENTINEL_SESSION


def test_security_levels_readable_by_admin(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    install_admin_fakes(monkeypatch, captured)
    response = admin_client(client_factory).get("/v1/admin/security-levels")
    body = response.json()
    assert response.status_code == 200
    assert body[0]["name"] == "internal"
    assert body[0]["rank"] == 2


def test_security_levels_have_no_mutation_routes(client: Any) -> None:
    methods: set[str] = set()
    for path, ops in client.app.openapi()["paths"].items():
        if path.startswith("/v1/admin/security-levels"):
            methods |= {method.upper() for method in ops}
    assert methods == {"GET"}
