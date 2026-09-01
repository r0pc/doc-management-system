# ruff: noqa: B008 -- Depends() in argument defaults is the FastAPI idiom;
# the Annotated[] form fails to resolve under CPython 3.14 PEP 649 lazy
# annotations with fastapi 0.141 (ForwardRef evaluation bug).

"""The departments a caller may assign a document to.

Feeds the upload picker and the admin re-assignment controls. It deliberately
returns only what the caller could actually save — their own visible subtree
plus the mandatory tenant root — so the UI cannot offer a choice the server
will reject, and cannot enumerate the rest of the organisation's structure.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api import deps
from app.db.departments import assignable_department_ids, root_department_id
from app.db.models import Department
from app.domain.models import Action, UserCtx

router = APIRouter(tags=["departments"])


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    #: The tenant root. Every document must belong to it, so the UI pre-selects
    #: it and refuses to let it be cleared.
    is_root: bool
    #: False when the caller may see the department but not assign into it.
    assignable: bool


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(
    user: UserCtx = Depends(deps.require(Action.VIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> list[DepartmentOut]:
    async with sessions(user.tenant_id) as session:
        assignable = await assignable_department_ids(session, user)
        root = await root_department_id(session, user.tenant_id)
        rows = (
            await session.execute(
                select(Department.id, Department.name, Department.parent_id)
                .where(Department.id.in_(assignable))
                .order_by(Department.parent_id.is_(None).desc(), Department.name.asc())
            )
        ).all()
    return [
        DepartmentOut(
            id=row[0],
            name=row[1],
            parent_id=row[2],
            is_root=row[0] == root,
            assignable=row[0] in assignable,
        )
        for row in rows
    ]
