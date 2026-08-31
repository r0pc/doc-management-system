# ruff: noqa: B008 -- Depends() in argument defaults is the FastAPI idiom;
# the Annotated[] form fails to resolve under CPython 3.14 PEP 649 lazy
# annotations with fastapi 0.141 (ForwardRef evaluation bug).


"""Document endpoints: list, detail, split-path content, findings, jobs, reclassify.

Authorization pattern (all resource routes): fetch through an RLS-bound
session — foreign-tenant rows read as missing — then re-check
``policy.can_access`` server-side (#33). Missing, foreign, deleted and
denied-deny all collapse into errors.not_found() so bodies are byte-stable
across tenants and causes (#31); timing parity holds because every path runs
the identical fetch→gate→respond sequence with no existence-dependent branch.

Content split (#17): Confidential/Restricted bytes stream through the API
with Range support; Public/Internal redirect (303) to a presigned URL whose
TTL is clamped to 60-120s. The audit row is written and committed in the same
transaction as the authorization decision BEFORE bytes stream (#30): the
commit records that access was granted; streaming then proceeds outside the
session. Range on the presigned path is out of scope this phase (MinIO-native
range via URL params) and is ignored rather than mis-applied.

Human reclassification (#2/#8/#20/#21): inserts an append-only classifications
row scoped to the CURRENT version, moves the documents pointer, closes pending
review items and writes the audit row — all in ONE transaction. The DB
``check_monotonic`` trigger remains the monotonicity authority and permits the
human-decided lowering that workers can never perform (#8).
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, BinaryIO, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, insert, or_, select, tuple_, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_416_RANGE_NOT_SATISFIABLE

from app.api import deps
from app.api.v1.errors import not_found
from app.classification.pipeline import ml_threshold_from_env
from app.config import Settings
from app.db.models import (
    Blob,
    Classification,
    DocType,
    Document,
    DocumentKeyword,
    DocumentVersion,
    Finding,
    Keyword,
    ProcessingJob,
    ReviewItem,
    SecurityLevel,
)
from app.domain.models import (
    DEFAULT_FLOOR_RANK,
    LEVEL_RANK,
    Action,
    DocumentRef,
    LevelName,
    UserCtx,
)
from app.domain.policy import can_access
from app.storage.base import Storage
from app.storage.keys import derived_key

DOCUMENT_STATUSES = ("quarantined", "processing", "ready", "failed", "held")

# allow: SIZE_OK - the whole /v1/documents resource surface (6 endpoints,
# wire models, cursor/range codecs, data-access seams) lives here because
# this wave's file whitelist forbids new modules. Planned split with the
# repositories expansion (Wave 5): fetch seams -> db/repositories/, cursor
# codec -> api/v1/pagination.py.
router = APIRouter(prefix="/documents", tags=["documents"])

_STREAM_CHUNK_BYTES = 64 * 1024
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

STAGE_ORDER: dict[str, int] = {
    "scan": 0,
    "extract": 1,
    "keywords": 2,
    "embed": 3,
    "classify": 4,
    "index": 5,
}


# --- wire models ---


class DocumentListItem(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    level: str | None
    doc_type: str | None
    created_at: datetime
    duplicate_of: list[uuid.UUID] = []


class DocumentPage(BaseModel):
    items: list[DocumentListItem]
    next_cursor: str | None


class FindingOut(BaseModel):
    entity_type: str
    rule_id: str
    page_no: int | None
    char_start: int
    char_end: int
    score: float
    line_no: int | None = None
    snippet: str | None = None
    contributed_level: str | None = None


class PageTextOut(BaseModel):
    page_no: int
    text: str


class ClassificationJustification(BaseModel):
    level: str
    level_rank: int
    level_reason: str
    doc_type: str | None
    decided_by: str
    confidence: float | None
    confidence_threshold: float
    keywords: list[str]
    findings: list[FindingOut]


class DocumentPreviewOut(BaseModel):
    id: uuid.UUID
    filename: str
    mime: str | None
    char_count: int
    pages: list[PageTextOut]
    full_text: str
    justification: ClassificationJustification


class JobOut(BaseModel):
    stage: str
    state: str
    attempts: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class ReclassifyRequest(BaseModel):
    level_name: LevelName
    doc_type_id: uuid.UUID | None = None


class LabelView(BaseModel):
    document_id: uuid.UUID
    level: str
    doc_type_id: uuid.UUID | None
    decided_by: str


# --- internal projections ---


@dataclass(frozen=True, slots=True)
class DocumentView:
    """Everything authorization and serving need about one document."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    department_id: uuid.UUID | None
    level_rank: int | None
    deleted_at: datetime | None
    status: str
    original_filename: str
    created_at: datetime
    level_name: str | None
    doc_type_name: str | None
    blob_key: str | None
    blob_mime: str | None
    blob_size: int | None
    current_version_id: uuid.UUID | None
    blob_sha256: str | None = None
    decided_by: str | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ReclassifyContext:
    view: DocumentView
    current_version_id: uuid.UUID


# --- helpers for snippet and line computation ---


def _compute_line_no(text: str, char_idx: int) -> int:
    return text[:char_idx].count("\n") + 1


def _compute_snippet(text: str, start: int, end: int, window: int = 40) -> str:
    snippet_start = max(0, start - window)
    snippet_end = min(len(text), end + window)
    prefix = "..." if snippet_start > 0 else ""
    suffix = "..." if snippet_end < len(text) else ""
    return f"{prefix}{text[snippet_start:snippet_end]}{suffix}"


def _contributed_level(entity_type: str, count: int = 1) -> str:
    if entity_type in (
        "card_number",
        "bank_account",
        "passport_number",
        "salary_with_named_person",
    ):
        return "Restricted"
    if entity_type == "cnic":
        return "Restricted" if count >= 3 else "Confidential"
    return "Internal"


def _build_level_reason(level_name: str | None, findings: list[FindingOut]) -> str:
    if not findings:
        return (
            "Internal: Default floor (no sensitive PII entities detected). "
            "Baseline organizational clearance."
        )
    types_detected = sorted({f.entity_type.replace("_", " ").title() for f in findings})
    types_str = ", ".join(types_detected)
    return (
        f"{level_name or 'Restricted'}: Triggered by {len(findings)} sensitive "
        f"pattern match(es) ({types_str})."
    )


# --- cursor codec (opaque, keyset on (created_at, id)) ---


def encode_cursor(created_at: datetime, document_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{document_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(token: str) -> tuple[datetime, uuid.UUID]:
    # Broad except is deliberate: b64/isodatetime/uuid failures all mean the
    # same thing — an unusable cursor — and none may leak decoder internals.
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        ts_text, id_text = raw.split("|", 1)
        return datetime.fromisoformat(ts_text), uuid.UUID(id_text)
    except Exception as exc:
        raise HTTPException(HTTP_400_BAD_REQUEST, "invalid cursor") from exc


# --- Range parsing ---


_RANGE_RE = re.compile(r"bytes=(?P<start>\d+)?-(?P<end>\d+)?")


def parse_range(header_value: str | None, total: int) -> tuple[int, int] | None:
    """Parse HTTP Range header supporting closed, open-ended, and suffix forms."""
    if not header_value:
        return None
    match = _RANGE_RE.fullmatch(header_value.strip())
    if match is None:
        return None
    start_str = match.group("start")
    end_str = match.group("end")
    if not start_str and not end_str:
        return None
    if start_str and end_str:
        start, end = int(start_str), int(end_str)
    elif start_str and not end_str:
        start, end = int(start_str), total - 1
    else:
        # Suffix range: bytes=-500 means last 500 bytes
        suffix = int(end_str)
        start = max(0, total - suffix)
        end = total - 1

    if start > end or start >= total:
        raise HTTPException(
            HTTP_416_RANGE_NOT_SATISFIABLE,
            "requested range not satisfiable",
            headers={"Content-Range": f"bytes */{total}"},
        )
    return start, min(end, total - 1)


# --- data-access seams (monkeypatched in unit tests; SQL proven Wave 5) ---


async def _fetch_document_page(
    session: AsyncSession,
    user: UserCtx,
    after: tuple[datetime, uuid.UUID] | None,
    limit_plus_one: int,
    *,
    status: str | None = None,
    level: str | None = None,
) -> list[DocumentListItem]:
    """Keyset page filtered by BOTH access axes inside the query (#25/#27)."""
    stmt = (
        select(
            Document.id,
            Document.original_filename,
            Document.status,
            SecurityLevel.name.label("level_name"),
            DocType.name.label("doc_type_name"),
            Document.created_at,
        )
        .join(
            Classification,
            Document.current_classification_id == Classification.id,
            isouter=True,
        )
        .join(SecurityLevel, Classification.level_id == SecurityLevel.id, isouter=True)
        .join(DocType, Classification.doc_type_id == DocType.id, isouter=True)
        .where(
            Document.tenant_id == user.tenant_id,
            Document.deleted_at.is_(None),
            func.coalesce(SecurityLevel.rank, DEFAULT_FLOOR_RANK) <= user.clearance_rank,
        )
        .order_by(Document.created_at.asc(), Document.id.asc())
    )
    if status is not None:
        stmt = stmt.where(Document.status == status)
    if level is not None:
        stmt = stmt.where(SecurityLevel.name == level)
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
        stmt = stmt.where(tuple_(Document.created_at, Document.id) > after)
    
    stmt = stmt.limit(limit_plus_one)
    rows = (await session.execute(stmt)).all()
    return [
        DocumentListItem(
            id=row.id,
            filename=row.original_filename,
            status=row.status,
            level=row.level_name,
            doc_type=row.doc_type_name,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def _fetch_content_siblings(
    session: AsyncSession, document_id: uuid.UUID, tenant_id: uuid.UUID
) -> list[uuid.UUID]:
    """Other visible documents in this tenant sharing this document's bytes.

    Content dedup already happens at the blob layer; this only tells the user
    the duplicate exists. Scoped to the tenant and to non-deleted rows, so it
    reveals nothing the list endpoint would not (#15: the object key is never
    an authorization boundary — permission lives on the documents row).
    """
    this_sha = (
        select(DocumentVersion.blob_sha256)
        .where(DocumentVersion.document_id == document_id)
        .scalar_subquery()
    )
    stmt = (
        select(Document.id)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .where(
            DocumentVersion.blob_sha256 == this_sha,
            DocumentVersion.blob_sha256.is_not(None),
            Document.id != document_id,
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def _fetch_document_view(
    session: AsyncSession, document_id: uuid.UUID
) -> DocumentView | None:
    row = (
        await session.execute(
            select(
                Document.id,
                Document.tenant_id,
                Document.department_id,
                SecurityLevel.rank,
                Document.deleted_at,
                Document.status,
                Document.original_filename,
                Document.created_at,
                SecurityLevel.name.label("level_name"),
                DocType.name.label("doc_type_name"),
                Blob.bucket_key,
                Blob.mime_sniffed,
                Blob.size_bytes,
                DocumentVersion.id.label("version_id"),
                DocumentVersion.blob_sha256,
                Classification.decided_by,
                Classification.confidence,
            )
            .join(
                Classification,
                Document.current_classification_id == Classification.id,
                isouter=True,
            )
            .join(SecurityLevel, Classification.level_id == SecurityLevel.id, isouter=True)
            .join(DocType, Classification.doc_type_id == DocType.id, isouter=True)
            .join(
                DocumentVersion,
                or_(
                    Classification.version_id == DocumentVersion.id,
                    and_(
                        Classification.id.is_(None),
                        DocumentVersion.document_id == Document.id,
                    ),
                ),
                isouter=True,
            )
            .join(Blob, DocumentVersion.blob_sha256 == Blob.sha256, isouter=True)
            .where(Document.id == document_id)
        )
    ).first()
    if row is None:
        return None
    return DocumentView(*row)


async def _fetch_keywords(session: AsyncSession, document_id: uuid.UUID) -> list[str]:
    stmt = (
        select(Keyword.term)
        .join(DocumentKeyword, Keyword.id == DocumentKeyword.keyword_id)
        .where(DocumentKeyword.document_id == document_id)
        .order_by(DocumentKeyword.score.desc())
        .limit(10)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def _fetch_findings(session: AsyncSession, document_id: uuid.UUID) -> list[FindingOut]:
    """Offsets only — matched text never leaves the findings table (#12)."""
    rows = (
        await session.execute(
            select(
                Finding.entity_type,
                Finding.rule_id,
                Finding.page_no,
                Finding.char_start,
                Finding.char_end,
                Finding.score,
            )
            .join(Classification, Finding.classification_id == Classification.id)
            .where(Classification.document_id == document_id)
            .order_by(Finding.char_start.asc())
        )
    ).all()
    return [
        FindingOut(
            entity_type=row.entity_type,
            rule_id=row.rule_id,
            page_no=row.page_no,
            char_start=row.char_start,
            char_end=row.char_end,
            score=row.score,
        )
        for row in rows
    ]


async def _fetch_jobs(session: AsyncSession, document_id: uuid.UUID) -> list[JobOut]:
    rows = (
        await session.execute(
            select(
                ProcessingJob.stage,
                ProcessingJob.state,
                ProcessingJob.attempts,
                ProcessingJob.error,
                ProcessingJob.started_at,
                ProcessingJob.finished_at,
            ).where(ProcessingJob.document_id == document_id)
        )
    ).all()
    jobs = [
        JobOut(
            stage=row.stage,
            state=row.state,
            attempts=row.attempts,
            error=row.error,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )
        for row in rows
    ]
    ceiling = len(STAGE_ORDER)
    jobs.sort(key=lambda job: (STAGE_ORDER.get(job.stage, ceiling), job.stage))
    return jobs


async def _load_reclassify_context(
    session: AsyncSession, document_id: uuid.UUID
) -> ReclassifyContext | None:
    view = await _fetch_document_view(session, document_id)
    if view is None or view.current_version_id is None:
        return None
    return ReclassifyContext(view=view, current_version_id=view.current_version_id)


async def _resolve_level_id(session: AsyncSession, name: LevelName) -> uuid.UUID | None:
    row = (
        await session.execute(
            select(SecurityLevel.id).where(func.lower(SecurityLevel.name) == name.value.lower())
        )
    ).first()
    return row[0] if row else None


async def _doc_type_exists(session: AsyncSession, doc_type_id: uuid.UUID) -> bool:
    row = (await session.execute(select(DocType.id).where(DocType.id == doc_type_id))).first()
    return row is not None


async def _apply_human_classification(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    level_id: uuid.UUID,
    doc_type_id: uuid.UUID | None,
) -> uuid.UUID:
    """Append-only insert (#20) scoped to the version (#21); pointer move.

    The check_monotonic DB trigger stays the sole monotonicity authority and
    admits decided_by='human' lowerings that automated layers can never make
    (#8).
    """
    classification_id = uuid.uuid4()
    await session.execute(
        insert(Classification).values(
            id=classification_id,
            document_id=document_id,
            version_id=version_id,
            level_id=level_id,
            doc_type_id=doc_type_id,
            confidence=None,
            decided_by="human",
        )
    )
    await session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(current_classification_id=classification_id)
    )
    return classification_id


async def _close_pending_reviews(session: AsyncSession, document_id: uuid.UUID) -> int:
    result = await session.execute(
        update(ReviewItem)
        .where(ReviewItem.document_id == document_id, ReviewItem.state == "pending")
        .values(state="resolved", resolved_at=datetime.now(tz=UTC))
    )
    rowcount = cast("CursorResult[Any]", result).rowcount
    return int(rowcount or 0)


# --- handlers ---


@router.get("", response_model=DocumentPage)
async def list_documents(
    user: UserCtx = Depends(deps.require(Action.VIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(default=None),
    status: Literal[DOCUMENT_STATUSES] | None = Query(default=None),  # type: ignore[valid-type]
    security_level: LevelName | None = Query(default=None),
) -> DocumentPage:
    """Keyset pagination over documents. Cursor is an opaque token."""
    after = decode_cursor(cursor) if cursor is not None else None
    async with sessions(user.tenant_id) as session:
        rows = await _fetch_document_page(
            session, user, after, limit + 1, status=status, level=security_level
        )
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None
    return DocumentPage(items=page, next_cursor=next_cursor)


def _denied(view: DocumentView | None, user: UserCtx, action: Action) -> bool:
    """Single gate: missing / deleted / two-axis denial all look identical."""
    if view is None or view.deleted_at is not None:
        return True
    ref = DocumentRef(
        id=view.id,
        tenant_id=view.tenant_id,
        department_id=view.department_id,
        level_rank=view.level_rank if view.level_rank is not None else DEFAULT_FLOOR_RANK,
        deleted_at=view.deleted_at,
    )
    return not can_access(user, ref, action)


@router.get("/{document_id}", response_model=DocumentListItem)
async def get_document(
    document_id: uuid.UUID,
    user: UserCtx = Depends(deps.require(Action.VIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> DocumentListItem | Response:
    async with sessions(user.tenant_id) as session:
        view = await _fetch_document_view(session, document_id)
        if _denied(view, user, Action.VIEW) or view is None:
            return not_found()
        siblings = await _fetch_content_siblings(session, document_id, user.tenant_id)
        return DocumentListItem(
            id=view.id,
            filename=view.original_filename,
            status=view.status,
            level=view.level_name,
            doc_type=view.doc_type_name,
            created_at=view.created_at,
            duplicate_of=siblings,
        )


def _stream_handle(handle: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := handle.read(_STREAM_CHUNK_BYTES):
            yield chunk
    finally:
        handle.close()


def _ensure_filename_extension(filename: str, mime: str | None) -> str:
    cleaned = filename.strip() or "document"
    if "." in cleaned:
        return cleaned
    if mime == "application/pdf":
        return f"{cleaned}.pdf"
    if mime == "text/plain":
        return f"{cleaned}.txt"
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return f"{cleaned}.docx"
    if mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return f"{cleaned}.xlsx"
    return cleaned


@router.get("/{document_id}/content")
async def download_document_content(
    request: Request,
    document_id: uuid.UUID,
    user: UserCtx = Depends(deps.require(Action.DOWNLOAD)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    settings: Settings = Depends(deps.get_settings),
    storage: Storage = Depends(deps.get_storage),
) -> Response:
    """Byte-serving endpoint (§6.3, Invariants #17, #18, #30)."""
    async with sessions(user.tenant_id) as session:
        view = await _fetch_document_view(session, document_id)
        if _denied(view, user, Action.DOWNLOAD) or view is None:
            return not_found()
        if view.blob_key is None:
            return not_found()
        download_name = _ensure_filename_extension(view.original_filename, view.blob_mime)
        total = view.blob_size or 0
        rank = view.level_rank if view.level_rank is not None else DEFAULT_FLOOR_RANK
        if rank >= LEVEL_RANK[LevelName.CONFIDENTIAL]:
            byte_range = parse_range(request.headers.get("range"), total)
            handle = storage.open(view.blob_key, byte_range=byte_range)
            length = total if byte_range is None else byte_range[1] - byte_range[0] + 1
            headers = {
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Disposition": f'attachment; filename="{download_name}"',
            }
            status = 200
            if byte_range is not None:
                status = 206
                headers["Content-Range"] = f"bytes {byte_range[0]}-{byte_range[1]}/{total}"
            # Audit commits WITH the authorization decision, before streaming;
            # the generator below runs outside the session deliberately (#30).
            actor_id = await deps.provision_actor(session, user)
            await deps.record_audit(
                session,
                tenant_id=user.tenant_id,
                document_id=view.id,
                actor_id=actor_id,
                action="download.stream",
                request=request,
            )
            await session.commit()
            return StreamingResponse(
                _stream_handle(handle),
                status_code=status,
                media_type=view.blob_mime or "application/octet-stream",
                headers=headers,
            )
        url = storage.presign(
            view.blob_key,
            settings.presign_ttl_seconds,
            filename=download_name,
        )
        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=view.id,
            actor_id=actor_id,
            action="download.presign",
            request=request,
        )
        await session.commit()
        return RedirectResponse(url, status_code=303)


@router.get("/{document_id}/view")
async def view_document_content(
    request: Request,
    document_id: uuid.UUID,
    user: UserCtx = Depends(deps.require(Action.PREVIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    settings: Settings = Depends(deps.get_settings),
    storage: Storage = Depends(deps.get_storage),
) -> Response:
    """Inline view for in-browser inspection (Action.PREVIEW - Invariant #18)."""
    async with sessions(user.tenant_id) as session:
        view = await _fetch_document_view(session, document_id)
        if _denied(view, user, Action.PREVIEW) or view is None:
            return not_found()
        if view.blob_key is None:
            return not_found()
        view_name = _ensure_filename_extension(view.original_filename, view.blob_mime)
        total = view.blob_size or 0
        rank = view.level_rank if view.level_rank is not None else DEFAULT_FLOOR_RANK
        if rank >= LEVEL_RANK[LevelName.CONFIDENTIAL]:
            byte_range = parse_range(request.headers.get("range"), total)
            handle = storage.open(view.blob_key, byte_range=byte_range)
            length = total if byte_range is None else byte_range[1] - byte_range[0] + 1
            headers = {
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Disposition": f'inline; filename="{view_name}"',
            }
            status = 200
            if byte_range is not None:
                status = 206
                headers["Content-Range"] = f"bytes {byte_range[0]}-{byte_range[1]}/{total}"
            actor_id = await deps.provision_actor(session, user)
            await deps.record_audit(
                session,
                tenant_id=user.tenant_id,
                document_id=view.id,
                actor_id=actor_id,
                action="preview.stream",
                request=request,
            )
            await session.commit()
            return StreamingResponse(
                _stream_handle(handle),
                status_code=status,
                media_type=view.blob_mime or "application/octet-stream",
                headers=headers,
            )
        url = storage.presign(
            view.blob_key,
            settings.presign_ttl_seconds,
            filename=view_name,
        )
        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=view.id,
            actor_id=actor_id,
            action="preview.presign",
            request=request,
        )
        await session.commit()
        return RedirectResponse(url, status_code=303)


@router.get("/{document_id}/preview", response_model=DocumentPreviewOut)
async def get_document_preview(
    request: Request,
    document_id: uuid.UUID,
    user: UserCtx = Depends(deps.require(Action.PREVIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    storage: Storage = Depends(deps.get_storage),
) -> DocumentPreviewOut | Response:
    """Full text, page structure, and classification justification (Action.PREVIEW)."""
    async with sessions(user.tenant_id) as session:
        view = await _fetch_document_view(session, document_id)
        if _denied(view, user, Action.PREVIEW) or view is None:
            return not_found()

        raw_findings = await _fetch_findings(session, document_id)
        keywords = await _fetch_keywords(session, document_id)

        full_text = ""
        pages: list[PageTextOut] = []
        char_count = 0

        if view.blob_sha256:
            try:
                derived_path = derived_key(view.blob_sha256, "text.json")
                with storage.open(derived_path) as handle:
                    data = json.loads(handle.read().decode("utf-8"))
                    full_text = str(data.get("text", ""))
                    char_count = int(data.get("char_count", len(full_text)))
                    for p in data.get("pages", []):
                        pages.append(
                            PageTextOut(
                                page_no=p.get("page_no", 1),
                                text=p.get("text", ""),
                            )
                        )
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                full_text = ""

        if not pages and full_text:
            pages = [PageTextOut(page_no=1, text=full_text)]

        cnic_count = sum(1 for f in raw_findings if f.entity_type == "cnic")
        enriched_findings: list[FindingOut] = []
        for f in raw_findings:
            line_no = _compute_line_no(full_text, f.char_start) if full_text else None
            snippet = _compute_snippet(full_text, f.char_start, f.char_end) if full_text else None
            level = _contributed_level(f.entity_type, cnic_count)
            enriched_findings.append(
                FindingOut(
                    entity_type=f.entity_type,
                    rule_id=f.rule_id,
                    page_no=f.page_no,
                    char_start=f.char_start,
                    char_end=f.char_end,
                    score=f.score,
                    line_no=line_no,
                    snippet=snippet,
                    contributed_level=level,
                )
            )

        level_name = view.level_name or "Internal"
        level_rank = view.level_rank or DEFAULT_FLOOR_RANK
        level_reason = _build_level_reason(level_name, enriched_findings)

        threshold = ml_threshold_from_env()

        justification = ClassificationJustification(
            level=level_name,
            level_rank=level_rank,
            level_reason=level_reason,
            doc_type=view.doc_type_name,
            decided_by=view.decided_by or "rules",
            confidence=view.confidence,
            confidence_threshold=threshold,
            keywords=keywords,
            findings=enriched_findings,
        )

        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=view.id,
            actor_id=actor_id,
            action="preview.read",
            request=request,
        )
        await session.commit()

        return DocumentPreviewOut(
            id=view.id,
            filename=view.original_filename,
            mime=view.blob_mime,
            char_count=char_count,
            pages=pages,
            full_text=full_text,
            justification=justification,
        )


@router.get("/{document_id}/findings", response_model=list[FindingOut])
async def get_document_findings(
    request: Request,
    document_id: uuid.UUID,
    user: UserCtx = Depends(deps.require(Action.PREVIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    storage: Storage = Depends(deps.get_storage),
) -> list[FindingOut] | Response:
    async with sessions(user.tenant_id) as session:
        view = await _fetch_document_view(session, document_id)
        if _denied(view, user, Action.PREVIEW) or view is None:
            return not_found()
        raw_findings = await _fetch_findings(session, document_id)

        full_text = ""
        if view.blob_sha256:
            try:
                derived_path = derived_key(view.blob_sha256, "text.json")
                with storage.open(derived_path) as handle:
                    data = json.loads(handle.read().decode("utf-8"))
                    full_text = str(data.get("text", ""))
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                full_text = ""

        cnic_count = sum(1 for f in raw_findings if f.entity_type == "cnic")
        enriched: list[FindingOut] = []
        for f in raw_findings:
            line_no = _compute_line_no(full_text, f.char_start) if full_text else None
            snippet = _compute_snippet(full_text, f.char_start, f.char_end) if full_text else None
            level = _contributed_level(f.entity_type, cnic_count)
            enriched.append(
                FindingOut(
                    entity_type=f.entity_type,
                    rule_id=f.rule_id,
                    page_no=f.page_no,
                    char_start=f.char_start,
                    char_end=f.char_end,
                    score=f.score,
                    line_no=line_no,
                    snippet=snippet,
                    contributed_level=level,
                )
            )

        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=view.id,
            actor_id=actor_id,
            action="findings.read",
            request=request,
        )
        await session.commit()
        return enriched


@router.get("/{document_id}/jobs", response_model=list[JobOut])
async def get_document_jobs(
    request: Request,
    document_id: uuid.UUID,
    user: UserCtx = Depends(deps.require(Action.VIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> list[JobOut] | Response:
    async with sessions(user.tenant_id) as session:
        view = await _fetch_document_view(session, document_id)
        if _denied(view, user, Action.VIEW) or view is None:
            return not_found()
        jobs = await _fetch_jobs(session, document_id)
        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=view.id,
            actor_id=actor_id,
            action="jobs.read",
            request=request,
        )
        await session.commit()
        return jobs


@router.post("/{document_id}/classification", response_model=LabelView)
async def reclassify_document(
    request: Request,
    document_id: uuid.UUID,
    payload: ReclassifyRequest,
    user: UserCtx = Depends(deps.require(Action.RECLASSIFY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> LabelView | Response:
    async with sessions(user.tenant_id) as session:
        context = await _load_reclassify_context(session, document_id)
        if context is None or _denied(context.view, user, Action.RECLASSIFY):
            return not_found()
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
            version_id=context.current_version_id,
            level_id=level_id,
            doc_type_id=payload.doc_type_id,
        )
        await _close_pending_reviews(session, context.view.id)
        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=context.view.id,
            actor_id=actor_id,
            action="reclassify.human",
            request=request,
        )
        await session.commit()
    return LabelView(
        document_id=context.view.id,
        level=payload.level_name.value,
        doc_type_id=payload.doc_type_id,
        decided_by="human",
    )
