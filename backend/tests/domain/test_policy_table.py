"""Parametrised authorisation truth table for domain.policy.can_access.

Two independent axes (AGENTS.md #25): clearance rank ("how sensitive") and
department visibility ("whose business"). Role never gates on its own.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.domain.models import Action, DocumentRef, UserCtx
from app.domain.policy import can_access

T1 = uuid.uuid5(uuid.NAMESPACE_URL, "tenant-1")
T2 = uuid.uuid5(uuid.NAMESPACE_URL, "tenant-2")
D1 = uuid.uuid5(uuid.NAMESPACE_URL, "division-1")
D2 = uuid.uuid5(uuid.NAMESPACE_URL, "division-2")

DELETED_TS = datetime(2026, 1, 1, tzinfo=UTC)


def make_user(
    tenant: uuid.UUID = T1,
    department: uuid.UUID | None = D1,
    clearance: int = 4,
    role: str = "manager",
    visible: tuple[uuid.UUID, ...] = (D1,),
) -> UserCtx:
    return UserCtx(
        tenant_id=tenant,
        department_id=department,
        clearance_rank=clearance,
        role=role,
        sub="user-1",
        visible_department_ids=visible,
    )


def make_doc(
    tenant: uuid.UUID = T1,
    department: uuid.UUID | None = D1,
    level_rank: int = 2,
    deleted_at: datetime | None = None,
) -> DocumentRef:
    return DocumentRef(
        id=uuid.uuid5(uuid.NAMESPACE_URL, "doc-1"),
        tenant_id=tenant,
        department_id=department,
        level_rank=level_rank,
        deleted_at=deleted_at,
    )


@pytest.mark.parametrize(
    ("user_kwargs", "doc_kwargs", "expected"),
    [
        # Happy path: manager, own division, Restricted doc.
        (
            {"clearance": 4, "visible": (D1,)},
            {"level_rank": 4, "department": D1},
            True,
        ),
        # Spec case A: senior manager WITH Restricted clearance cannot read another
        # division's disciplinary files — department axis blocks despite rank 4.
        (
            {"clearance": 4, "role": "senior_manager", "visible": (D1,)},
            {"level_rank": 4, "department": D2},
            False,
        ),
        # Visibility covering the subtree unlocks the other-division document.
        (
            {"clearance": 4, "visible": (D1, D2)},
            {"level_rank": 4, "department": D2},
            True,
        ),
        # Junior clerk, insufficient clearance: blocked even in own department.
        (
            {"clearance": 1, "role": "clerk", "visible": (D1,)},
            {"level_rank": 4, "department": D1},
            False,
        ),
        # Spec case B: junior clerk with adequate clearance reads own-dept
        # Confidential file — role alone never gates; both axes pass.
        (
            {"clearance": 3, "role": "clerk", "visible": (D1,)},
            {"level_rank": 3, "department": D1},
            True,
        ),
        # Public doc with no owning department is open to any clearance >= 1.
        (
            {"clearance": 1, "visible": (D1,)},
            {"level_rank": 1, "department": None},
            True,
        ),
        # Boundary equality: clearance == level passes.
        (
            {"clearance": 1, "visible": (D1,)},
            {"level_rank": 1, "department": D1},
            True,
        ),
        # No owning department does NOT bypass the clearance axis.
        (
            {"clearance": 2, "visible": (D1,)},
            {"level_rank": 3, "department": None},
            False,
        ),
        # Cross-tenant is denied even for a Public, department-less document.
        (
            {"tenant": T2, "clearance": 4, "visible": (D1,)},
            {"level_rank": 1, "department": None},
            False,
        ),
        # Soft-deleted documents are denied regardless of everything else.
        (
            {"clearance": 4, "visible": (D1,)},
            {"level_rank": 1, "department": None, "deleted_at": DELETED_TS},
            False,
        ),
        # Empty visibility set denies any department-scoped document.
        (
            {"clearance": 4, "visible": ()},
            {"level_rank": 2, "department": D1},
            False,
        ),
        # Internal floor document, own department, sufficient clearance.
        (
            {"clearance": 4, "visible": (D1,)},
            {"level_rank": 2, "department": D1},
            True,
        ),
        # No owning department does not bypass the level axis either.
        (
            {"clearance": 3, "visible": (D1,)},
            {"level_rank": 4, "department": None},
            False,
        ),
    ],
)
def test_can_access_table(
    user_kwargs: dict[str, Any],
    doc_kwargs: dict[str, Any],
    expected: bool,
) -> None:
    user = make_user(**user_kwargs)
    doc = make_doc(**doc_kwargs)
    assert can_access(user, doc, Action.VIEW) is expected


@pytest.mark.parametrize("action", list(Action))
def test_all_actions_allowed_when_both_axes_pass(action: Action) -> None:
    user = make_user(clearance=4, visible=(D1,))
    doc = make_doc(level_rank=4, department=D1)
    assert can_access(user, doc, action) is True


@pytest.mark.parametrize("action", list(Action))
def test_all_actions_denied_on_cross_tenant(action: Action) -> None:
    user = make_user(tenant=T2, clearance=4, visible=(D1,))
    doc = make_doc(level_rank=1, department=None)
    assert can_access(user, doc, action) is False
