"""Reading and writing a document's department membership.

Membership is an authorisation input: adding a department grants everyone in
that subtree sight of the document. So every write goes through
:func:`replace_document_departments`, and every write is validated against
:func:`assignable_department_ids` first — a caller must not be able to hand a
document to a department they cannot see themselves.

The tenant root is mandatory on every document (:func:`root_department_id`).
Without that rule a document could be scoped to a leaf department and become
invisible to the top of the organisation, including to the admins responsible
for it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Department, DocumentDepartment
from app.domain.models import UserCtx


async def root_department_id(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID | None:
    """The tenant's root department (``parent_id IS NULL``), or None if unseeded."""
    return (
        await session.execute(
            select(Department.id).where(
                Department.tenant_id == tenant_id,
                Department.parent_id.is_(None),
            )
        )
    ).scalar_one_or_none()


async def assignable_department_ids(session: AsyncSession, user: UserCtx) -> set[uuid.UUID]:
    """Departments this caller may put a document into.

    Their own visible subtree, plus the root — the root is required on every
    document, so a caller who could not assign it could never save at all.
    """
    allowed = set(user.visible_department_ids)
    root = await root_department_id(session, user.tenant_id)
    if root is not None:
        allowed.add(root)
    return allowed


async def load_document_departments(
    session: AsyncSession, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Current membership for each document, for display."""
    rows = (
        await session.execute(
            select(DocumentDepartment.document_id, DocumentDepartment.department_id).where(
                DocumentDepartment.document_id.in_(document_ids)
            )
        )
    ).all()
    out: dict[uuid.UUID, list[uuid.UUID]] = {doc_id: [] for doc_id in document_ids}
    for doc_id, dept_id in rows:
        out.setdefault(doc_id, []).append(dept_id)
    return out


async def replace_document_departments(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    department_ids: set[uuid.UUID],
) -> None:
    """Set membership for these documents to exactly ``department_ids``.

    Delete-then-insert rather than a diff: the caller states the whole set, and
    computing a minimal delta would leave a window in which a document belonged
    to neither the old nor the new departments. Both statements run in the
    caller's transaction, so the swap is atomic.
    """
    if not document_ids or not department_ids:
        return
    await session.execute(
        delete(DocumentDepartment).where(DocumentDepartment.document_id.in_(document_ids))
    )
    await session.execute(
        pg_insert(DocumentDepartment)
        .values(
            [
                {
                    "document_id": document_id,
                    "department_id": department_id,
                    "tenant_id": tenant_id,
                }
                for document_id in document_ids
                for department_id in sorted(department_ids)
            ]
        )
        .on_conflict_do_nothing()
    )


__all__ = [
    "assignable_department_ids",
    "load_document_departments",
    "replace_document_departments",
    "root_department_id",
]
