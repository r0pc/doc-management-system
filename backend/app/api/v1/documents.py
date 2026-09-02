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
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, BinaryIO, Final, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, insert, or_, select, tuple_, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_416_RANGE_NOT_SATISFIABLE

from app.api import deps
from app.api.v1.content_safety import SAFE_CONTENT_HEADERS, safe_inline_delivery
from app.api.v1.errors import not_found
from app.classification.pipeline import ml_threshold_from_env
from app.config import Settings
from app.db.departments import (
    assignable_department_ids,
    replace_document_departments,
    root_department_id,
)
from app.db.models import (
    Blob,
    Classification,
    Department,
    DocType,
    Document,
    DocumentDepartment,
    DocumentKeyword,
    DocumentVersion,
    Finding,
    Keyword,
    ProcessingJob,
    ReviewItem,
    SecurityLevel,
)
from app.db.visibility import department_clause
from app.domain.models import (
    DEFAULT_FLOOR_RANK,
    LEVEL_RANK,
    Action,
    DocumentRef,
    LevelName,
    UserCtx,
)
from app.domain.policy import can_access
from app.domain.taxonomy import CNIC_ENTITY_TYPE, CNIC_RESTRICTED_COUNT, Taxonomy
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
    level_rank: int | None = None
    #: Departments the document belongs to. Populated on BOTH the list and the
    #: detail route: a field that is silently empty on one of them is the kind
    #: of "looks populated" bug this codebase keeps finding.
    department_ids: list[uuid.UUID] = []


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
    justification: str | None = Field(None, max_length=1000)


class AutoClassifyRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class AutoClassifyResponse(BaseModel):
    reclassified: list[uuid.UUID]


class SetDepartmentsRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    #: The complete set the documents should end up in, not a delta. The tenant
    #: root must be present; the server refuses the write otherwise.
    department_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class SetDepartmentsResponse(BaseModel):
    """Only the documents actually re-assigned (#31, as for delete)."""

    updated: list[uuid.UUID]
    department_ids: list[uuid.UUID]


class DeleteRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class DeleteResponse(BaseModel):
    """Only what was actually deleted.

    #31: a caller must not learn whether an id they could not delete was
    foreign, nonexistent, or denied. Reporting those separately would turn this
    route into an existence oracle over other tenants, so anything not deleted
    is simply absent from the response.
    """

    deleted: list[uuid.UUID]


class LabelView(BaseModel):
    document_id: uuid.UUID
    level: str
    doc_type_id: uuid.UUID | None
    decided_by: str


class StatusBreakdown(BaseModel):
    ready: int = 0
    processing: int = 0
    quarantined: int = 0
    failed: int = 0
    held: int = 0


class LevelStat(BaseModel):
    name: str
    rank: int
    count: int
    percentage: float


class DocTypeStat(BaseModel):
    name: str
    count: int
    percentage: float


class DepartmentStat(BaseModel):
    id: uuid.UUID
    name: str
    count: int


class DecisionSourceStat(BaseModel):
    source: str
    count: int


class DailyIngestionStat(BaseModel):
    date: str
    count: int


class RecentDocumentStat(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    level: str | None
    doc_type: str | None
    created_at: datetime


class DocumentStatsOut(BaseModel):
    total_documents: int
    total_storage_bytes: int
    status_breakdown: StatusBreakdown
    levels_breakdown: list[LevelStat]
    doc_types_breakdown: list[DocTypeStat]
    departments_breakdown: list[DepartmentStat]
    decision_sources: list[DecisionSourceStat]
    daily_ingestion: list[DailyIngestionStat]
    recent_documents: list[RecentDocumentStat]
    avg_confidence: float | None
    pending_reviews_count: int


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
    #: Every department this document belongs to; empty means tenant-wide.
    department_ids: frozenset[uuid.UUID] = frozenset()


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


_RANK_TO_NAME: Final[dict[int, str]] = {
    1: "Public",
    2: "Internal",
    3: "Confidential",
    4: "Restricted",
}


def _contributed_level(
    entity_type: str,
    count: int = 1,
    custom_ranks: Mapping[str, int] | None = None,
) -> str:
    tax = Taxonomy.for_tenant(custom_ranks) if custom_ranks is not None else Taxonomy.default()
    if entity_type == CNIC_ENTITY_TYPE and count >= CNIC_RESTRICTED_COUNT:
        return "Restricted"
    rank = tax.entity_rank.get(entity_type, 2)
    return _RANK_TO_NAME.get(rank, "Internal")


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


SortField = Literal["created_at", "filename", "status", "level", "doc_type"]
SortDirection = Literal["asc", "desc"]

SORT_FIELDS: Final[tuple[str, ...]] = (
    "created_at",
    "filename",
    "status",
    "level",
    "doc_type",
)


@dataclass(frozen=True)
class SortCursor:
    """A keyset position: which sort produced it, and where it stopped.

    The sort travels INSIDE the token so a page cannot be interpreted under a
    different sort than the one that produced it — that would silently skip or
    repeat rows across a page boundary (#32).
    """

    field: str
    direction: str
    value: datetime | str | int | None
    document_id: uuid.UUID


def encode_cursor(
    sort_field: str,
    direction: str,
    sort_value: datetime | str | int | None,
    document_id: uuid.UUID,
) -> str:
    kind: str
    val: Any
    if isinstance(sort_value, datetime):
        kind = "dt"
        val = sort_value.isoformat()
    elif isinstance(sort_value, int):
        kind = "i"
        val = sort_value
    elif sort_value is None:
        kind = "null"
        val = None
    else:
        kind = "s"
        val = str(sort_value)
    payload = {
        "f": sort_field,
        "d": direction,
        "v": val,
        "t": kind,
        "i": str(document_id),
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(token: str) -> SortCursor:
    # Broad except is deliberate: b64/json/isoformat/uuid failures all mean the
    # same thing — an unusable cursor — and none may leak decoder internals.
    try:
        raw = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        field, direction, kind = raw["f"], raw["d"], raw["t"]
        if field not in SORT_FIELDS or direction not in ("asc", "desc"):
            raise ValueError("unknown sort")
        value: datetime | str | int | None
        if kind == "dt":
            value = datetime.fromisoformat(raw["v"])
        elif kind == "i":
            value = int(raw["v"])
        elif kind == "null":
            value = None
        else:
            value = str(raw["v"])
        return SortCursor(field, direction, value, uuid.UUID(raw["i"]))
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


def _sort_expression(sort_field: str) -> Any:
    """The ORDER BY / keyset expression for a sort column.

    Nullable columns are coalesced to an explicit sentinel so unclassified rows
    sort predictably and — critically — so the keyset comparison is never NULL.
    `(NULL, id) > (value, id)` evaluates to NULL, not false, which silently
    DROPS those rows at a page boundary instead of ordering them (#32).

    level coalesces to DEFAULT_FLOOR_RANK because that is the rank an
    unclassified document is actually authorised at (#9) — sorting it anywhere
    else would disagree with how it is treated.
    """
    if sort_field == "created_at":
        return Document.created_at
    if sort_field == "filename":
        return Document.original_filename
    if sort_field == "status":
        return Document.status
    if sort_field == "level":
        return func.coalesce(SecurityLevel.rank, DEFAULT_FLOOR_RANK)
    if sort_field == "doc_type":
        return func.coalesce(DocType.name, "")
    msg = f"unsortable field: {sort_field}"
    raise ValueError(msg)


def _null_sentinel(sort_field: str) -> Any:
    """The value a NULL sort key was coalesced to, for cursor comparison."""
    return DEFAULT_FLOOR_RANK if sort_field == "level" else ""


def _sort_value_of(item: DocumentListItem, sort_field: str) -> datetime | str | int | None:
    if sort_field == "created_at":
        return item.created_at
    if sort_field == "filename":
        return item.filename
    if sort_field == "status":
        return item.status
    if sort_field == "level":
        return item.level_rank if item.level_rank is not None else DEFAULT_FLOOR_RANK
    if sort_field == "doc_type":
        return item.doc_type
    msg = f"unknown sort field: {sort_field}"
    raise ValueError(msg)


async def _fetch_document_page(
    session: AsyncSession,
    user: UserCtx,
    after: SortCursor | None,
    limit_plus_one: int,
    *,
    status: str | None = None,
    level: str | None = None,
    sort_field: str = "created_at",
    direction: str = "asc",
) -> list[DocumentListItem]:
    """Keyset page filtered by BOTH access axes inside the query (#25/#27)."""
    sort_col = _sort_expression(sort_field)
    ascending = direction == "asc"
    order = (
        (sort_col.asc(), Document.id.asc()) if ascending else (sort_col.desc(), Document.id.desc())
    )

    stmt = (
        select(
            Document.id,
            Document.original_filename,
            Document.status,
            SecurityLevel.name.label("level_name"),
            DocType.name.label("doc_type_name"),
            Document.created_at,
            select(func.array_agg(DocumentDepartment.department_id))
            .where(DocumentDepartment.document_id == Document.id)
            .scalar_subquery()
            .label("department_ids"),
            SecurityLevel.rank.label("level_rank"),
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
    )
    if status is not None:
        stmt = stmt.where(Document.status == status)
    if level is not None:
        stmt = stmt.where(SecurityLevel.name == level)
    stmt = stmt.where(department_clause(user))
    if after is not None:
        anchor = after.value if after.value is not None else _null_sentinel(sort_field)
        keyset = tuple_(sort_col, Document.id)
        stmt = stmt.where(
            keyset > (anchor, after.document_id)
            if ascending
            else keyset < (anchor, after.document_id)
        )

    stmt = stmt.order_by(*order).limit(limit_plus_one)
    rows = (await session.execute(stmt)).all()
    return [
        DocumentListItem(
            id=row.id,
            filename=row.original_filename,
            status=row.status,
            level=row.level_name,
            doc_type=row.doc_type_name,
            created_at=row.created_at,
            level_rank=row.level_rank,
            department_ids=list(row.department_ids or ()),
        )
        for row in rows
    ]


async def _fetch_document_stats(session: AsyncSession, user: UserCtx) -> DocumentStatsOut:
    base_stmt = (
        select(
            Document.id,
            Document.original_filename,
            Document.status,
            Document.created_at,
            SecurityLevel.name.label("level_name"),
            SecurityLevel.rank.label("level_rank"),
            DocType.name.label("doc_type_name"),
            Classification.decided_by,
            Classification.confidence,
            Blob.size_bytes,
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
        .where(
            Document.tenant_id == user.tenant_id,
            Document.deleted_at.is_(None),
            func.coalesce(SecurityLevel.rank, DEFAULT_FLOOR_RANK) <= user.clearance_rank,
            department_clause(user),
        )
    )
    rows = (await session.execute(base_stmt)).all()
    total_documents = len(rows)
    total_storage_bytes = sum(r.size_bytes or 0 for r in rows)

    status_counts = Counter(r.status for r in rows)
    status_breakdown = StatusBreakdown(
        ready=status_counts.get("ready", 0),
        processing=status_counts.get("processing", 0),
        quarantined=status_counts.get("quarantined", 0),
        failed=status_counts.get("failed", 0),
        held=status_counts.get("held", 0),
    )

    level_names = [("Public", 1), ("Internal", 2), ("Confidential", 3), ("Restricted", 4)]
    level_counts = Counter(r.level_name or "Internal" for r in rows)
    levels_breakdown = [
        LevelStat(
            name=name,
            rank=rank,
            count=level_counts.get(name, 0),
            percentage=round((level_counts.get(name, 0) / total_documents * 100), 1)
            if total_documents > 0
            else 0.0,
        )
        for name, rank in level_names
    ]

    doc_type_counts = Counter(r.doc_type_name or "Uncategorized" for r in rows)
    doc_types_breakdown = [
        DocTypeStat(
            name=dt_name,
            count=count,
            percentage=round((count / total_documents * 100), 1) if total_documents > 0 else 0.0,
        )
        for dt_name, count in doc_type_counts.most_common(10)
    ]

    source_counts = Counter(r.decided_by or "default" for r in rows)
    decision_sources = [
        DecisionSourceStat(source=source, count=count)
        for source, count in sorted(source_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    confidences = [r.confidence for r in rows if r.confidence is not None]
    avg_confidence = round(sum(confidences) / len(confidences), 3) if confidences else None

    daily_counter = Counter(r.created_at.strftime("%Y-%m-%d") for r in rows)
    daily_ingestion = [
        DailyIngestionStat(date=d, count=c) for d, c in sorted(daily_counter.items())[-14:]
    ]

    sorted_recent = sorted(rows, key=lambda r: r.created_at, reverse=True)[:5]
    recent_documents = [
        RecentDocumentStat(
            id=r.id,
            filename=r.original_filename,
            status=r.status,
            level=r.level_name or "Internal",
            doc_type=r.doc_type_name,
            created_at=r.created_at,
        )
        for r in sorted_recent
    ]

    doc_ids = [r.id for r in rows]
    dept_stats: list[DepartmentStat] = []
    if doc_ids:
        dept_rows = (
            await session.execute(
                select(Department.id, Department.name, func.count(DocumentDepartment.document_id))
                .join(DocumentDepartment, DocumentDepartment.department_id == Department.id)
                .where(
                    DocumentDepartment.document_id.in_(doc_ids),
                    Department.tenant_id == user.tenant_id,
                )
                .group_by(Department.id, Department.name)
                .order_by(Department.name.asc())
            )
        ).all()
        dept_stats = [DepartmentStat(id=row[0], name=row[1], count=row[2]) for row in dept_rows]

    pending_reviews_stmt = (
        select(func.count(ReviewItem.id))
        .join(Document, ReviewItem.document_id == Document.id)
        .join(
            Classification,
            Document.current_classification_id == Classification.id,
            isouter=True,
        )
        .join(SecurityLevel, Classification.level_id == SecurityLevel.id, isouter=True)
        .where(
            Document.tenant_id == user.tenant_id,
            ReviewItem.state == "pending",
            Document.deleted_at.is_(None),
            func.coalesce(SecurityLevel.rank, DEFAULT_FLOOR_RANK) <= user.clearance_rank,
            department_clause(user),
        )
    )
    pending_reviews_count = int((await session.execute(pending_reviews_stmt)).scalar_one() or 0)

    return DocumentStatsOut(
        total_documents=total_documents,
        total_storage_bytes=total_storage_bytes,
        status_breakdown=status_breakdown,
        levels_breakdown=levels_breakdown,
        doc_types_breakdown=doc_types_breakdown,
        departments_breakdown=dept_stats,
        decision_sources=decision_sources,
        daily_ingestion=daily_ingestion,
        recent_documents=recent_documents,
        avg_confidence=avg_confidence,
        pending_reviews_count=pending_reviews_count,
    )


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
                # Aggregated, not joined: a join would multiply the row per
                # department and DocumentView unpacks exactly one.
                select(func.array_agg(DocumentDepartment.department_id))
                .where(DocumentDepartment.document_id == Document.id)
                .scalar_subquery()
                .label("department_ids"),
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
    # array_agg yields NULL, not an empty array, when the document belongs to
    # no department — which is the tenant-wide case, not an error. Rewriting the
    # value in place keeps the positional unpack, which is what pins the select
    # column order to the dataclass field order.
    values = list(row)
    values[-1] = frozenset(values[-1] or ())
    return DocumentView(*values)


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


async def _fetch_deletable_document_ids(
    session: AsyncSession, user: UserCtx, document_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """The subset of ``document_ids`` this caller may actually delete.

    Filters on the same two axes every other read does (#25) and skips rows
    already deleted, so a repeat call is a no-op rather than a second audit
    row. Anything foreign, missing or denied simply does not come back.
    """
    stmt = (
        select(Document.id)
        .join(
            Classification,
            Document.current_classification_id == Classification.id,
            isouter=True,
        )
        .join(SecurityLevel, Classification.level_id == SecurityLevel.id, isouter=True)
        .where(
            Document.id.in_(document_ids),
            Document.tenant_id == user.tenant_id,
            Document.deleted_at.is_(None),
            func.coalesce(SecurityLevel.rank, DEFAULT_FLOOR_RANK) <= user.clearance_rank,
        )
    )
    stmt = stmt.where(department_clause(user))
    return list((await session.execute(stmt)).scalars().all())


async def _soft_delete_documents(session: AsyncSession, document_ids: list[uuid.UUID]) -> None:
    """Stamp ``deleted_at``. Never a hard delete.

    classifications.document_id is a foreign key into an append-only table
    (#20) and the app role holds no DELETE grant on access_log (#24), so
    removing the row is neither possible nor desirable. Every read path
    already filters on deleted_at IS NULL.
    """
    await session.execute(
        update(Document).where(Document.id.in_(document_ids)).values(deleted_at=func.now())
    )


@router.post("/delete", response_model=DeleteResponse)
async def delete_documents(
    request: Request,
    payload: DeleteRequest,
    user: UserCtx = Depends(deps.require(Action.DELETE)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> DeleteResponse:
    """Soft-delete a selection of documents.

    Registered before ``/{document_id}`` reads it as a path parameter; the
    method differs so there is no capture, but keep it above them regardless.

    The audit rows and the deletion share one transaction (#30), and only ids
    that were genuinely deleted are audited or returned (#31).
    """
    # Deduplicate but keep the caller's order, so the response reads back the
    # way the selection was made.
    unique_ids = list(dict.fromkeys(payload.document_ids))
    async with sessions(user.tenant_id) as session:
        deletable = await _fetch_deletable_document_ids(session, user, unique_ids)
        if deletable:
            await _soft_delete_documents(session, deletable)
            actor_id = await deps.provision_actor(session, user)
            for document_id in deletable:
                await deps.record_audit(
                    session,
                    tenant_id=user.tenant_id,
                    document_id=document_id,
                    actor_id=actor_id,
                    action="document.delete",
                    request=request,
                )
        await session.commit()
    ordered = [d for d in unique_ids if d in set(deletable)]
    return DeleteResponse(deleted=ordered)


@router.post("/departments", response_model=SetDepartmentsResponse)
async def set_document_departments(
    request: Request,
    payload: SetDepartmentsRequest,
    user: UserCtx = Depends(deps.require(Action.MANAGE_DEPARTMENTS)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> SetDepartmentsResponse:
    """Replace the departments a selection of documents belongs to.

    Registered above ``/{document_id}`` for the same reason as ``/delete``.

    Two rules are enforced server-side, not merely in the picker. The tenant
    root must be included, so no document can be scoped out of sight of the top
    of the organisation. And every department must be one the caller could
    assign — otherwise a caller could hand a document to a subtree they cannot
    see, granting access they do not themselves have.
    """
    unique_ids = list(dict.fromkeys(payload.document_ids))
    wanted = set(payload.department_ids)

    async with sessions(user.tenant_id) as session:
        root = await root_department_id(session, user.tenant_id)
        if root is None or root not in wanted:
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                "every document must belong to the root department",
            )
        allowed = await assignable_department_ids(session, user)
        if not wanted.issubset(allowed):
            # Deliberately does not name which id was rejected: the caller
            # cannot see those departments, so naming them enumerates the org.
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                "one or more departments are not assignable by this caller",
            )

        # Reuse the delete path's visibility filter: a caller may only re-assign
        # documents they can already see, and foreign ids simply do not come
        # back (#31).
        targets = await _fetch_deletable_document_ids(session, user, unique_ids)
        if targets:
            await replace_document_departments(
                session,
                tenant_id=user.tenant_id,
                document_ids=targets,
                department_ids=wanted,
            )
            actor_id = await deps.provision_actor(session, user)
            for document_id in targets:
                await deps.record_audit(
                    session,
                    tenant_id=user.tenant_id,
                    document_id=document_id,
                    actor_id=actor_id,
                    action="document.departments",
                    request=request,
                )
        await session.commit()

    ordered = [d for d in unique_ids if d in set(targets)]
    return SetDepartmentsResponse(updated=ordered, department_ids=sorted(wanted))


async def _fetch_reclassifiable_documents(
    session: AsyncSession, user: UserCtx, document_ids: list[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """The subset of ``document_ids`` this caller may reclassify, with their current version IDs.

    Filters on the same two axes every other read does (#25) and skips rows
    deleted or lacking a version. Foreign, missing or denied rows simply do not come back (#31).
    """
    stmt = (
        select(Document.id, DocumentVersion.id)
        .join(
            Classification,
            Document.current_classification_id == Classification.id,
            isouter=True,
        )
        .join(SecurityLevel, Classification.level_id == SecurityLevel.id, isouter=True)
        .join(
            DocumentVersion,
            DocumentVersion.document_id == Document.id,
        )
        .where(
            Document.id.in_(document_ids),
            Document.tenant_id == user.tenant_id,
            Document.deleted_at.is_(None),
            func.coalesce(SecurityLevel.rank, DEFAULT_FLOOR_RANK) <= user.clearance_rank,
        )
        .order_by(DocumentVersion.version_no.desc())
    )
    stmt = stmt.where(department_clause(user))
    rows = (await session.execute(stmt)).all()
    seen: set[uuid.UUID] = set()
    result: list[tuple[uuid.UUID, uuid.UUID]] = []
    for doc_id, ver_id in rows:
        if doc_id not in seen:
            seen.add(doc_id)
            result.append((doc_id, ver_id))
    return result


async def _mark_documents_processing(session: AsyncSession, document_ids: list[uuid.UUID]) -> None:
    await session.execute(
        update(Document).where(Document.id.in_(document_ids)).values(status="processing")
    )


def _enqueue_reclassify(document_id: uuid.UUID, version_id: uuid.UUID) -> None:
    from app.workers.tasks import reclassify_document_task

    reclassify_document_task.delay(str(document_id), str(version_id))


@router.post("/auto-classify", response_model=AutoClassifyResponse)
async def auto_classify_documents(
    request: Request,
    payload: AutoClassifyRequest,
    user: UserCtx = Depends(deps.require(Action.RECLASSIFY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> AutoClassifyResponse:
    """Pass selected documents through the automated classification pipeline again.

    The audit rows and status update share one transaction (#30), and only ids
    that were genuinely eligible are audited or returned (#31).
    Workers are the automated writer (#2).
    """
    unique_ids = list(dict.fromkeys(payload.document_ids))
    async with sessions(user.tenant_id) as session:
        eligible = await _fetch_reclassifiable_documents(session, user, unique_ids)
        doc_ids = [d[0] for d in eligible]
        if doc_ids:
            await _mark_documents_processing(session, doc_ids)
            actor_id = await deps.provision_actor(session, user)
            for document_id in doc_ids:
                await deps.record_audit(
                    session,
                    tenant_id=user.tenant_id,
                    document_id=document_id,
                    actor_id=actor_id,
                    action="reclassify.auto",
                    request=request,
                )
        await session.commit()

    for doc_id, ver_id in eligible:
        _enqueue_reclassify(doc_id, ver_id)

    ordered = [d for d in unique_ids if d in set(doc_ids)]
    return AutoClassifyResponse(reclassified=ordered)


@router.get("", response_model=DocumentPage)
async def list_documents(
    user: UserCtx = Depends(deps.require(Action.VIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(default=None),
    status: Literal[DOCUMENT_STATUSES] | None = Query(default=None),  # type: ignore[valid-type]
    security_level: LevelName | None = Query(default=None),
    sort: Literal["created_at", "filename", "status", "level", "doc_type"] | None = Query(
        default=None
    ),
    direction: Literal["asc", "desc"] = Query(default="asc"),
) -> DocumentPage:
    """Keyset pagination over documents. Cursor is an opaque token."""
    after = decode_cursor(cursor) if cursor is not None else None
    sort_field = sort or (after.field if after else "created_at")
    sort_dir = after.direction if after else direction
    if (
        after is not None
        and sort is not None
        and (sort != after.field or direction != after.direction)
    ):
        raise HTTPException(HTTP_400_BAD_REQUEST, "invalid cursor")

    async with sessions(user.tenant_id) as session:
        rows = await _fetch_document_page(
            session,
            user,
            after,
            limit + 1,
            status=status,
            level=security_level,
            sort_field=sort_field,
            direction=sort_dir,
        )
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = (
        encode_cursor(sort_field, sort_dir, _sort_value_of(page[-1], sort_field), page[-1].id)
        if has_more and page
        else None
    )
    return DocumentPage(items=page, next_cursor=next_cursor)


@router.get("/stats", response_model=DocumentStatsOut)
async def get_document_stats(
    user: UserCtx = Depends(deps.require(Action.VIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> DocumentStatsOut:
    """Aggregated stats and metrics for documents visible to this caller."""
    async with sessions(user.tenant_id) as session:
        return await _fetch_document_stats(session, user)


def _denied(view: DocumentView | None, user: UserCtx, action: Action) -> bool:
    """Single gate: missing / deleted / two-axis denial all look identical."""
    if view is None or view.deleted_at is not None:
        return True
    ref = DocumentRef(
        id=view.id,
        tenant_id=view.tenant_id,
        department_ids=view.department_ids,
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
            level_rank=view.level_rank,
            department_ids=sorted(view.department_ids),
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


def _not_ready(view: DocumentView) -> Response | None:
    if view.blob_key is None:
        if view.status in ("processing", "held", "failed", "quarantined"):
            return JSONResponse(
                status_code=409, content={"detail": f"document is still {view.status}"}
            )
        return not_found()
    return None


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
        if not_ready_resp := _not_ready(view):
            return not_ready_resp
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
        if not_ready_resp := _not_ready(view):
            return not_ready_resp
        if view.blob_key is None:
            return not_found()
        view_name = _ensure_filename_extension(view.original_filename, view.blob_mime)
        total = view.blob_size or 0
        rank = view.level_rank if view.level_rank is not None else DEFAULT_FLOOR_RANK
        if rank >= LEVEL_RANK[LevelName.CONFIDENTIAL]:
            byte_range = parse_range(request.headers.get("range"), total)
            handle = storage.open(view.blob_key, byte_range=byte_range)
            length = total if byte_range is None else byte_range[1] - byte_range[0] + 1
            # A blob is promoted during the scan stage and keeps its sniffed
            # mime even when extraction later fails, so text/html and
            # image/svg+xml blobs DO reach this route. Served inline they
            # execute, and the frontend's blob: URL inherits the app's origin.
            # Default-deny: only non-scriptable types stay inline.
            media_type, disposition = safe_inline_delivery(view.blob_mime, view_name)
            headers = {
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Disposition": disposition,
                **SAFE_CONTENT_HEADERS,
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
                media_type=media_type,
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
            detail=payload.justification,
        )
        await session.commit()
    return LabelView(
        document_id=context.view.id,
        level=payload.level_name.value,
        doc_type_id=payload.doc_type_id,
        decided_by="human",
    )
