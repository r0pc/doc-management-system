"""Re-assigning which departments a document belongs to.

Membership is an authorisation input: adding a department grants everyone in
that subtree sight of the document. So the two server-side rules matter more
than the endpoint itself.

The tenant root is mandatory. Without it a document could be scoped to a leaf
department and become invisible to the top of the organisation — including to
the admins accountable for it — and nothing would report that it had happened.

A caller may only assign departments they could see themselves. Otherwise the
route is an escalation primitive: hand a document to a subtree you have no
access to and you have granted access you do not hold.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.api.v1 import documents as documents_module

PATH = "/v1/documents/departments"

ROOT = uuid.UUID("c0000000-0000-0000-0000-000000000011")
HR = uuid.UUID("c0000000-0000-0000-0000-000000000012")
FOREIGN_DEPT = uuid.UUID("c0000000-0000-0000-0000-0000000000ff")

DOC_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
FOREIGN_DOC = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def assigned(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Captures what the route actually wrote, and gates what it may write."""
    record: dict[str, Any] = {}

    async def fake_root(session: Any, tenant_id: Any) -> uuid.UUID:
        return ROOT

    async def fake_assignable(session: Any, user: Any) -> set[uuid.UUID]:
        return {ROOT, HR}

    async def fake_targets(
        session: Any, user: Any, document_ids: list[uuid.UUID]
    ) -> list[uuid.UUID]:
        return [d for d in document_ids if d == DOC_A]

    async def fake_replace(
        session: Any,
        *,
        tenant_id: Any,
        document_ids: list[uuid.UUID],
        department_ids: set[uuid.UUID],
    ) -> None:
        record["documents"] = list(document_ids)
        record["departments"] = set(department_ids)

    monkeypatch.setattr(documents_module, "root_department_id", fake_root)
    monkeypatch.setattr(documents_module, "assignable_department_ids", fake_assignable)
    monkeypatch.setattr(documents_module, "_fetch_deletable_document_ids", fake_targets)
    monkeypatch.setattr(documents_module, "replace_document_departments", fake_replace)
    return record


def _post(client: Any, docs: list[uuid.UUID], depts: list[uuid.UUID]) -> Any:
    return client.post(
        PATH,
        json={"document_ids": [str(d) for d in docs], "department_ids": [str(d) for d in depts]},
    )


class TestHappyPath:
    def test_admin_can_share_a_document_with_a_second_department(
        self, client_factory: Any, assigned: dict[str, Any]
    ) -> None:
        client = client_factory(role="admin")
        response = _post(client, [DOC_A], [ROOT, HR])
        assert response.status_code == 200, response.text
        assert response.json()["updated"] == [str(DOC_A)]
        assert assigned["departments"] == {ROOT, HR}

    def test_the_root_alone_is_a_valid_set(
        self, client_factory: Any, assigned: dict[str, Any]
    ) -> None:
        client = client_factory(role="admin")
        assert _post(client, [DOC_A], [ROOT]).status_code == 200
        assert assigned["departments"] == {ROOT}

    def test_duplicate_ids_are_written_once(
        self, client_factory: Any, assigned: dict[str, Any]
    ) -> None:
        client = client_factory(role="admin")
        body = _post(client, [DOC_A, DOC_A], [ROOT, HR, HR]).json()
        assert body["updated"] == [str(DOC_A)]
        assert assigned["documents"] == [DOC_A]


class TestTheRootIsMandatory:
    def test_a_set_without_the_root_is_refused(
        self, client_factory: Any, assigned: dict[str, Any]
    ) -> None:
        """Otherwise a document can be scoped out of sight of the whole org."""
        client = client_factory(role="admin")
        response = _post(client, [DOC_A], [HR])
        assert response.status_code == 400
        assert assigned == {}, "a refused request still wrote membership"

    def test_an_empty_set_is_refused(self, client_factory: Any, assigned: dict[str, Any]) -> None:
        client = client_factory(role="admin")
        assert _post(client, [DOC_A], []).status_code == 400
        assert assigned == {}


class TestAssignabilityIsEnforced:
    def test_a_department_the_caller_cannot_see_is_refused(
        self, client_factory: Any, assigned: dict[str, Any]
    ) -> None:
        """Assigning into an invisible subtree would grant access the caller lacks."""
        client = client_factory(role="admin")
        response = _post(client, [DOC_A], [ROOT, FOREIGN_DEPT])
        assert response.status_code == 400
        assert assigned == {}

    def test_the_refusal_does_not_name_the_department(
        self, client_factory: Any, assigned: dict[str, Any]
    ) -> None:
        """Naming it would enumerate departments the caller cannot see."""
        client = client_factory(role="admin")
        body = _post(client, [DOC_A], [ROOT, FOREIGN_DEPT]).text
        assert str(FOREIGN_DEPT) not in body


class TestPermission:
    @pytest.mark.parametrize("role", ["security_officer", "dept_manager", "employee", "viewer"])
    def test_only_admin_may_re_assign(
        self, client_factory: Any, assigned: dict[str, Any], role: str
    ) -> None:
        client = client_factory(role=role)
        assert _post(client, [DOC_A], [ROOT, HR]).status_code == 403
        assert assigned == {}, "a refused caller still reached the write path"


class TestInvariant31:
    def test_a_document_the_caller_cannot_see_is_silently_absent(
        self, client_factory: Any, assigned: dict[str, Any]
    ) -> None:
        client = client_factory(role="admin")
        body = _post(client, [FOREIGN_DOC], [ROOT]).json()
        assert body["updated"] == []
        assert str(FOREIGN_DOC) not in str(body)

    def test_nothing_reports_why_an_id_was_skipped(
        self, client_factory: Any, assigned: dict[str, Any]
    ) -> None:
        client = client_factory(role="admin")
        body = _post(client, [DOC_A, FOREIGN_DOC], [ROOT]).json()
        assert body["updated"] == [str(DOC_A)]
        for key in ("denied", "not_found", "missing", "errors", "failed"):
            assert key not in body, f"{key} leaks why an id was skipped (#31)"


class TestAudit:
    def test_one_audit_row_per_document(
        self, client_factory: Any, assigned: dict[str, Any], journal: list[dict[str, Any]]
    ) -> None:
        """#30: the audit write shares the transaction with the action."""
        client = client_factory(role="admin")
        _post(client, [DOC_A], [ROOT, HR])
        rows = [e for e in journal if e["action"] == "document.departments"]
        assert len(rows) == 1
        assert rows[0]["document_id"] == DOC_A

    def test_nothing_assigned_writes_no_audit_row(
        self, client_factory: Any, assigned: dict[str, Any], journal: list[dict[str, Any]]
    ) -> None:
        client = client_factory(role="admin")
        _post(client, [FOREIGN_DOC], [ROOT])
        assert [e for e in journal if e["action"] == "document.departments"] == []
