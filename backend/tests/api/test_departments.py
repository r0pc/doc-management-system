"""Tests for department creation and listing endpoints (spec section 3.2, #25, #30)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.api.v1 import departments as departments_module

PATH = "/v1/departments"

TENANT_ID = uuid.UUID("a0000000-0000-0000-0000-000000000001")
ROOT_ID = uuid.UUID("c0000000-0000-0000-0000-000000000011")
HR_ID = uuid.UUID("c0000000-0000-0000-0000-000000000012")


class TestCreateDepartment:
    def test_admin_can_create_department(
        self, client_factory: Any, monkeypatch: pytest.MonkeyPatch, journal: list[dict[str, Any]]
    ) -> None:
        client = client_factory(role="admin")

        async def fake_root(session: Any, tenant_id: Any) -> uuid.UUID:
            return ROOT_ID

        class FakeResult:
            def scalar_one_or_none(self) -> Any:
                return ROOT_ID

            def first(self) -> Any:
                return None  # No duplicates

        async def fake_execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
            return FakeResult()

        monkeypatch.setattr(departments_module, "root_department_id", fake_root)
        from tests.api.conftest import SENTINEL_SESSION

        monkeypatch.setattr(SENTINEL_SESSION, "execute", fake_execute)
        added_objs: list[Any] = []
        monkeypatch.setattr(
            SENTINEL_SESSION, "add", lambda obj: added_objs.append(obj), raising=False
        )

        response = client.post(
            PATH,
            json={"name": "Engineering", "parent_id": str(ROOT_ID)},
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["name"] == "Engineering"
        assert data["parent_id"] == str(ROOT_ID)
        assert data["assignable"] is True
        assert data["is_root"] is False

        # Invariant #30: Audit trail written atomically
        audit_entries = [e for e in journal if e["action"] == "department.create"]
        assert len(audit_entries) == 1
        assert "name=Engineering" in audit_entries[0]["detail"]

    def test_non_admin_forbidden_from_creating_department(self, client_factory: Any) -> None:
        for role in ["security_officer", "dept_manager", "employee", "viewer"]:
            client = client_factory(role=role)
            response = client.post(
                PATH,
                json={"name": "Finance", "parent_id": str(ROOT_ID)},
            )
            assert response.status_code == 403

    def test_blank_name_rejected(
        self, client_factory: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = client_factory(role="admin")
        response = client.post(PATH, json={"name": "   ", "parent_id": str(ROOT_ID)})
        assert response.status_code == 422

    def test_duplicate_name_conflict_409(
        self, client_factory: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = client_factory(role="admin")

        async def fake_root(session: Any, tenant_id: Any) -> uuid.UUID:
            return ROOT_ID

        class DuplicateFoundResult:
            def scalar_one_or_none(self) -> Any:
                return ROOT_ID

            def first(self) -> Any:
                return (ROOT_ID,)  # Duplicate exists

        async def fake_execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
            return DuplicateFoundResult()

        monkeypatch.setattr(departments_module, "root_department_id", fake_root)
        from tests.api.conftest import SENTINEL_SESSION

        monkeypatch.setattr(SENTINEL_SESSION, "execute", fake_execute)
        monkeypatch.setattr(SENTINEL_SESSION, "add", lambda obj: None, raising=False)

        response = client.post(
            PATH,
            json={"name": "Human Resources", "parent_id": str(ROOT_ID)},
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]
