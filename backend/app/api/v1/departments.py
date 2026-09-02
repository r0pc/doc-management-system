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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.status import HTTP_409_CONFLICT

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


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    parent_id: uuid.UUID | None = None


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


@router.post("/departments", status_code=201, response_model=DepartmentOut)
async def create_department(
    request: Request,
    payload: DepartmentCreate,
    user: UserCtx = Depends(deps.require(Action.MANAGE_DEPARTMENTS)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> DepartmentOut:
    trimmed_name = payload.name.strip()
    if not trimmed_name:
        raise HTTPException(status_code=422, detail="Department name cannot be blank")

    async with sessions(user.tenant_id) as session:
        root_id = await root_department_id(session, user.tenant_id)
        parent_id = payload.parent_id
        if parent_id is None:
            # Default to attaching under the tenant's root department if one exists
            parent_id = root_id
        else:
            # Verify specified parent exists in this tenant
            parent_exists = (
                await session.execute(
                    select(Department.id).where(
                        Department.id == parent_id,
                        Department.tenant_id == user.tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if parent_exists is None:
                raise HTTPException(status_code=404, detail="Parent department not found")

        # Conflict check: unique name under the same parent for this tenant
        dup_stmt = select(Department.id).where(
            Department.tenant_id == user.tenant_id,
            Department.name == trimmed_name,
        )
        if parent_id is None:
            dup_stmt = dup_stmt.where(Department.parent_id.is_(None))
        else:
            dup_stmt = dup_stmt.where(Department.parent_id == parent_id)

        if (await session.execute(dup_stmt)).first() is not None:
            raise HTTPException(
                status_code=HTTP_409_CONFLICT,
                detail="A department with this name already exists under the selected parent",
            )

        new_id = uuid.uuid4()
        session.add(
            Department(
                id=new_id,
                tenant_id=user.tenant_id,
                parent_id=parent_id,
                name=trimmed_name,
            )
        )
        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=None,
            actor_id=actor_id,
            action="department.create",
            request=request,
            detail=f"name={trimmed_name},department_id={new_id},parent_id={parent_id}",
        )
        await session.commit()

        return DepartmentOut(
            id=new_id,
            name=trimmed_name,
            parent_id=parent_id,
            is_root=new_id == root_id,
            assignable=True,
        )
