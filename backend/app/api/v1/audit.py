# ruff: noqa: B008 -- Depends() in argument defaults is the FastAPI idiom;
# the Annotated[] form fails to resolve under CPython 3.14 PEP 649 lazy
# annotations with fastapi 0.141 (ForwardRef evaluation bug).


"""Read-only audit endpoints over ``access_log`` (invariant #24 posture).

This router defines GET routes ONLY — no POST/PUT/PATCH/DELETE exists anywhere
in this module, and none may be added: the application role holds no
UPDATE/DELETE grant on ``access_log`` and the audit trail is append-only by
construction (writes happen exclusively through ``deps.record_audit`` inside
the transaction of the action being recorded, #30). Reads are bare-column
selects — no joins needed since access_log carries bare uuids (#24).

Keyset pagination orders ``ts DESC, id DESC`` with the bigserial id as
tiebreaker; the limit CLAMPS to the ceiling rather than rejecting so audit
consumers never 400 on an oversized page request.
"""

import base64
import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.status import HTTP_400_BAD_REQUEST

from app.api import deps
from app.db.models import AccessLog
from app.domain.models import Action, UserCtx

router = APIRouter(prefix="/audit", tags=["audit"])

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


# --- wire models ---


class AuditLogEntry(BaseModel):
    id: int
    document_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    action: str
    ip: str | None
    user_agent: str | None
    ts: datetime


class AuditPage(BaseModel):
    items: list[AuditLogEntry]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class AuditFilters:
    """Exact-match filters; None means unfiltered on that axis."""

    document_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    action: str | None


# --- cursor codec (opaque, keyset on (ts DESC, id DESC); int bigserial ids) ---
# Near-duplicate of the documents codec by necessity: access_log.id is an int,
# not a uuid, and editing documents.py for a generic codec was out of scope.


def encode_log_cursor(ts: datetime, log_id: int) -> str:
    raw = f"{ts.isoformat()}|{log_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_log_cursor(token: str) -> tuple[datetime, int]:
    # Broad except is deliberate: b64/isodatetime/int failures all mean the
    # same thing — an unusable cursor — and none may leak decoder internals.
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        ts_text, id_text = raw.split("|", 1)
        return datetime.fromisoformat(ts_text), int(id_text)
    except Exception as exc:
        raise HTTPException(HTTP_400_BAD_REQUEST, "invalid cursor") from exc


# --- data-access seam (monkeypatched in unit tests; SQL proven Wave 5) ---


async def _fetch_audit_page(
    session: AsyncSession,
    filters: AuditFilters,
    after: tuple[datetime, int] | None,
    limit_plus_one: int,
) -> list[AuditLogEntry]:
    stmt = select(
        AccessLog.id,
        AccessLog.document_id,
        AccessLog.actor_id,
        AccessLog.action,
        AccessLog.ip,
        AccessLog.user_agent,
        AccessLog.ts,
    )
    if filters.document_id is not None:
        stmt = stmt.where(AccessLog.document_id == filters.document_id)
    if filters.actor_id is not None:
        stmt = stmt.where(AccessLog.actor_id == filters.actor_id)
    if filters.action is not None:
        stmt = stmt.where(AccessLog.action == filters.action)
    stmt = stmt.order_by(AccessLog.ts.desc(), AccessLog.id.desc()).limit(limit_plus_one)
    if after is not None:
        stmt = stmt.where(tuple_(AccessLog.ts, AccessLog.id) < after)
    rows = (await session.execute(stmt)).all()
    return [
        AuditLogEntry(
            id=row.id,
            document_id=row.document_id,
            actor_id=row.actor_id,
            action=row.action,
            ip=row.ip,
            user_agent=row.user_agent,
            ts=row.ts,
        )
        for row in rows
    ]


@router.get("", response_model=AuditPage)
async def list_audit_log(
    user: UserCtx = Depends(deps.require(Action.VIEW_AUDIT)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    document_id: uuid.UUID | None = Query(default=None),
    actor_id: uuid.UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1),
    cursor: str | None = Query(default=None),
) -> AuditPage:
    effective_limit = min(limit, MAX_PAGE_SIZE)
    after = decode_log_cursor(cursor) if cursor is not None else None
    filters = AuditFilters(document_id=document_id, actor_id=actor_id, action=action)
    async with sessions(user.tenant_id) as session:
        rows = await _fetch_audit_page(session, filters, after, effective_limit + 1)
    has_more = len(rows) > effective_limit
    page = rows[:effective_limit]
    next_cursor = encode_log_cursor(page[-1].ts, page[-1].id) if has_more and page else None
    return AuditPage(items=page, next_cursor=next_cursor)
