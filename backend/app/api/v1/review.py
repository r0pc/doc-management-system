# ruff: noqa: B008 -- Depends() in argument defaults is the FastAPI idiom;
# the Annotated[] form fails to resolve under CPython 3.14 PEP 649 lazy
# annotations with fastapi 0.141 (ForwardRef evaluation bug).


"""Review queue + human resolution endpoints (invariants #2, #8, #20, #21, #30).

Listing translates the documents-list visibility axes into SQL identically:
tenant equality, ``COALESCE(level_rank, 2) <= clearance``, department
null-or-visible, ``deleted_at IS NULL`` — applied INSIDE the page query,
before ranking/windowing (#25/#27). Keyset pagination reuses the documents
router's cursor codec verbatim (same (created_at, id) ordering).

Resolution delegates the classification write to the SAME transaction logic
the documents router uses for POST /{id}/classification
(``documents._apply_human_classification``): append-only insert scoped to the
current version (#20/#21), pointer move, THIS review item closed, audit row
written — all ONE transaction (#30). The DB ``check_monotonic`` trigger stays
the monotonicity authority and admits the human lowering workers can never
make (#8); prior classification rows are never touched.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select, tuple_, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_409_CONFLICT

from app.api import deps
from app.api.v1.documents import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    DocumentView,
    LabelView,
    _actor_uuid,
    _apply_human_classification,
    _denied,
    _doc_type_exists,
    _fetch_document_view,
    _resolve_level_id,
    decode_cursor,
    encode_cursor,
)
from app.api.v1.errors import not_found
from app.db.models import (
    Classification,
    DocType,
    Document,
    Finding,
    ReviewItem,
    SecurityLevel,
)
from app.domain.models import DEFAULT_FLOOR_RANK, Action, LevelName, UserCtx

router = APIRouter(prefix="/review", tags=["review"])


# --- wire models ---


class ReviewQueueItem(BaseModel):
    review_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    level: str | None
    doc_type: str | None
    confidence: float | None
    decided_by: str | None
    findings_count: int | None
    created_at: datetime


class ReviewPage(BaseModel):
    items: list[ReviewQueueItem]
    next_cursor: str | None


class ResolveReviewRequest(BaseModel):
    level_name: LevelName
    doc_type_id: uuid.UUID | None = None
    decision: Literal["accept", "correct"]


# --- internal projections ---


@dataclass(frozen=True, slots=True)
class ReviewContext:
    """The item plus everything authorization and the insert (#21) need."""

    review_id: uuid.UUID
    review_state: str
    view: DocumentView
    version_id: uuid.UUID


# --- data-access seams (monkeypatched in unit tests; SQL proven Wave 5) ---


async def _fetch_review_page(
    session: AsyncSession,
    user: UserCtx,
    after: tuple[datetime, uuid.UUID] | None,
    limit_plus_one: int,
) -> list[ReviewQueueItem]:
    """Pending items filtered by BOTH access axes inside the query (#25/#27)."""
    findings_count = (
        select(func.count())
        .select_from(Finding)
        .where(Finding.classification_id == Document.current_classification_id)
        .correlate(Document)
        .scalar_subquery()
    )
    stmt = (
        select(
            ReviewItem.id.label("review_id"),
            Document.id.label("document_id"),
            Document.original_filename.label("filename"),
            SecurityLevel.name.label("level"),
            DocType.name.label("doc_type"),
            Classification.confidence.label("confidence"),
            Classification.decided_by.label("decided_by"),
            ReviewItem.created_at.label("created_at"),
            findings_count.label("findings_count"),
        )
        .join(Document, ReviewItem.document_id == Document.id)
        .join(
            Classification,
            Document.current_classification_id == Classification.id,
            isouter=True,
        )
        .join(SecurityLevel, Classification.level_id == SecurityLevel.id, isouter=True)
        .join(DocType, Classification.doc_type_id == DocType.id, isouter=True)
        .where(
            ReviewItem.state == "pending",
            Document.tenant_id == user.tenant_id,
            Document.deleted_at.is_(None),
            func.coalesce(SecurityLevel.rank, DEFAULT_FLOOR_RANK) <= user.clearance_rank,
        )
        .order_by(ReviewItem.created_at.asc(), ReviewItem.id.asc())
        .limit(limit_plus_one)
    )
    if user.visible_department_ids:
        stmt = stmt.where(
            or_(
                Document.department_id.is_(None),
                Document.department_id.in_(user.visible_department_ids),
            )
        )
    else:
        stmt = stmt.where(Document.department_id.is_(None))
    if after is not None:
        stmt = stmt.where(tuple_(ReviewItem.created_at, ReviewItem.id) > after)
    rows = (await session.execute(stmt)).all()
    return [
        ReviewQueueItem(
            review_id=row.review_id,
            document_id=row.document_id,
            filename=row.filename,
            level=row.level,
            doc_type=row.doc_type,
            confidence=row.confidence,
            decided_by=row.decided_by,
            findings_count=row.findings_count,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def _fetch_review_context(session: AsyncSession, item_id: uuid.UUID) -> ReviewContext | None:
    """RLS scopes both reads; a foreign-tenant item or document reads as missing."""
    row = (
        await session.execute(
            select(ReviewItem.id, ReviewItem.document_id, ReviewItem.state).where(
                ReviewItem.id == item_id
            )
        )
    ).first()
    if row is None:
        return None
    view = await _fetch_document_view(session, row.document_id)
    # A document with no current version cannot be reclassified (#21) — same
    # guard _load_reclassify_context applies on the documents router.
    if view is None or view.current_version_id is None:
        return None
    return ReviewContext(
        review_id=row.id, review_state=row.state, view=view, version_id=view.current_version_id
    )


async def _close_review_item(session: AsyncSession, item_id: uuid.UUID) -> int:
    """Close exactly THIS item — never a blanket close over the document."""
    result = await session.execute(
        update(ReviewItem)
        .where(ReviewItem.id == item_id)
        .values(state="resolved", resolved_at=datetime.now(tz=UTC))
    )
    return int(cast("CursorResult[Any]", result).rowcount or 0)


# --- handlers ---


@router.get("", response_model=ReviewPage)
async def list_review_queue(
    user: UserCtx = Depends(deps.require(Action.RESOLVE_REVIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(default=None),
) -> ReviewPage:
    after = decode_cursor(cursor) if cursor is not None else None
    async with sessions(user.tenant_id) as session:
        rows = await _fetch_review_page(session, user, after, limit + 1)
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = (
        encode_cursor(page[-1].created_at, page[-1].review_id) if has_more and page else None
    )
    return ReviewPage(items=page, next_cursor=next_cursor)


@router.post("/{item_id}/resolve", response_model=LabelView)
async def resolve_review_item(
    request: Request,
    item_id: uuid.UUID,
    payload: ResolveReviewRequest,
    user: UserCtx = Depends(deps.require(Action.RESOLVE_REVIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> LabelView | Response:
    async with sessions(user.tenant_id) as session:
        context = await _fetch_review_context(session, item_id)
        if context is None or _denied(context.view, user, Action.RESOLVE_REVIEW):
            return not_found()
        if context.review_state != "pending":
            raise HTTPException(HTTP_409_CONFLICT, "review item is not pending")
        level_id = await _resolve_level_id(session, payload.level_name)
        if level_id is None:
            raise HTTPException(HTTP_400_BAD_REQUEST, "unknown security level")
        if payload.doc_type_id is not None and not await _doc_type_exists(
            session, payload.doc_type_id
        ):
            raise HTTPException(HTTP_400_BAD_REQUEST, "unknown document type")
        await _apply_human_classification(
            session,
            document_id=context.view.id,
            version_id=context.version_id,
            level_id=level_id,
            doc_type_id=payload.doc_type_id,
        )
        await _close_review_item(session, item_id)
        await deps.record_audit(
            session,
            document_id=context.view.id,
            actor_id=_actor_uuid(user),
            action="reclassify.resolve.human",
            request=request,
        )
        await session.commit()
    return LabelView(
        document_id=context.view.id,
        level=payload.level_name.value,
        doc_type_id=payload.doc_type_id,
        decided_by="human",
    )
