"""The department axis of #25, as one SQL clause.

This predicate decides who can see a document. It was written out by hand in
five places — the document list, the deletable and reclassifiable subsets, the
review queue, and both arms of hybrid search — which means a change to the
department model had five chances to be applied inconsistently, and a missed
one widens access silently rather than failing.

It lives here so there is exactly one of it. :func:`app.domain.policy.can_access`
is the same rule over an in-memory identity and stays pure; these two are
deliberate mirrors and are asserted to agree in
``tests/db/test_visibility_clause.py``.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, Select, or_, select

from app.db.models import Document, DocumentDepartment
from app.domain.models import UserCtx


def _memberships() -> Select[tuple[int]]:
    """Rows of ``document_departments`` for the document in the outer query."""
    return select(1).where(DocumentDepartment.document_id == Document.id)


def department_clause(user: UserCtx) -> ColumnElement[bool]:
    """Documents this caller may see on the department axis.

    A document belonging to no department is tenant-wide. Otherwise ANY of its
    departments being in the caller's visible subtree admits it — that is what
    lets a document be shared with a second department without leaving the one
    that owns it. A caller with no department sees only the tenant-wide ones.

    Reads ``document_departments`` and never ``documents.department_id``. The
    latter records who OWNS a document and is shown in the UI; if both were
    consulted they could disagree, and a disagreement about an authorisation
    input resolves as wider access, silently.
    """
    unscoped: ColumnElement[bool] = ~_memberships().exists()
    if not user.visible_department_ids:
        return unscoped
    return or_(
        unscoped,
        _memberships()
        .where(DocumentDepartment.department_id.in_(user.visible_department_ids))
        .exists(),
    )


__all__ = ["department_clause"]
