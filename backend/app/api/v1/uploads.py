# ruff: noqa: B008 -- Depends() in argument defaults is the FastAPI idiom;
# the Annotated[] form fails to resolve under CPython 3.14 PEP 649 lazy
# annotations with fastapi 0.141 (ForwardRef evaluation bug).


"""Upload endpoints: presigned intent + completion (invariants #1, #3, #5, #19).

Flow: ``POST /v1/uploads`` records intent — a ``quarantined`` documents row
plus a presigned PUT for the browser to hit object storage directly; the API
never touches bytes on the write path (#1). ``POST /v1/uploads/{id}/complete``
checks metadata (existence and declared size mismatch) ONCE, records version 1
and flips status to ``processing``, then enqueues the worker chain. Sniffing
the MIME type from content alone (#19), hashing sha256, and promoting the blob
into the immutable primary bucket (#16) happen in the worker.

Broker-failure decision (per wave instructions): if enqueueing the pipeline
chain fails — the task module is absent this wave or the broker is down — the
API returns 503 but the committed state stays ``processing``; a worker-side
reconciler picks stranded rows up later. Persistence intentionally commits
BEFORE the enqueue attempt so the audit row and state transition are atomic
(#30) while the queue write is best-effort.

The declared size travels with the client: intent validates it against the
cap, completion re-verifies actual bytes against it (413 on mismatch) and
against the cap regardless.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_409_CONFLICT,
    HTTP_413_CONTENT_TOO_LARGE,
    HTTP_422_UNPROCESSABLE_CONTENT,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from app.api import deps
from app.api.v1.errors import not_found
from app.config import Settings
from app.db.departments import (
    assignable_department_ids,
    replace_document_departments,
    root_department_id,
)
from app.db.models import Document, DocumentDepartment, DocumentVersion
from app.domain.models import DEFAULT_FLOOR_RANK, Action, DocumentRef, UserCtx
from app.domain.policy import can_access
from app.storage.base import Storage
from app.storage.keys import quarantine_key

logger = logging.getLogger(__name__)

# allow: SIZE_OK - single upload resource surface (2 endpoints + ingest
# helpers); the file whitelist for this wave forbids new modules. The
# _ingest/_persist seams move into db/repositories when that package
# expands (Wave 5), which brings this file back under the ceiling.
router = APIRouter(prefix="/uploads", tags=["uploads"])


class UploadIntentRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(ge=1)
    content_type: str = Field(min_length=1)
    #: Departments the document should belong to. Omitted means "the uploader's
    #: own department", which is the pre-existing behaviour. The tenant root is
    #: always added server-side, so it cannot be omitted by a crafted client.
    department_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)


class CompleteRequest(BaseModel):
    size_bytes: int | None = Field(default=None, ge=1)


class PresignedPut(BaseModel):
    url: str
    fields: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


class UploadIntentResponse(BaseModel):
    upload_id: uuid.UUID
    presigned_put: PresignedPut


class BatchFileRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(ge=1)
    content_type: str = Field(min_length=1)


class BatchUploadRequest(BaseModel):
    files: list[BatchFileRequest] = Field(min_length=1)
    #: Applies to every file in the batch; see UploadIntentRequest.
    department_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)


class BatchUploadResponse(BaseModel):
    batch_id: uuid.UUID
    uploads: list[UploadIntentResponse]


class CompleteResponse(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    status: str
    duplicate_of: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class QuarantinedDoc:
    """Minimal projection of a documents row at completion time."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    department_id: uuid.UUID | None
    original_filename: str
    status: str
    deleted_at: datetime | None
    #: Every department the document belongs to; empty means tenant-wide.
    department_ids: frozenset[uuid.UUID] = frozenset()


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of the single read over quarantined bytes."""

    sha256: str
    size_bytes: int
    mime: str
    object_key: str


async def _provision_actor(session: AsyncSession, user: UserCtx) -> uuid.UUID:
    return await deps.provision_actor(session, user)


async def _resolve_departments(
    session: AsyncSession, user: UserCtx, requested: list[uuid.UUID] | None
) -> set[uuid.UUID]:
    """The department set a new document should be created with.

    The tenant root is added unconditionally rather than validated, so no
    client — crafted or merely stale — can produce a document the top of the
    organisation cannot see. Anything else must be assignable by this caller;
    a request naming a department they cannot see is refused rather than
    quietly dropped, because silently narrowing a share is its own surprise.
    """
    allowed = await assignable_department_ids(session, user)
    chosen = set(requested) if requested else set()
    if not chosen and user.department_id is not None:
        chosen = {user.department_id}
    if not chosen.issubset(allowed):
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            "one or more departments are not assignable by this caller",
        )
    root = await root_department_id(session, user.tenant_id)
    if root is not None:
        chosen.add(root)
    return chosen


async def _insert_quarantine_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    user: UserCtx,
    filename: str,
    actor_id: uuid.UUID,
    department_ids: set[uuid.UUID] | None = None,
) -> None:
    await session.execute(
        insert(Document).values(
            id=document_id,
            tenant_id=user.tenant_id,
            # Still the OWNING department (who uploaded it). Visibility is
            # decided by document_departments alone.
            department_id=user.department_id,
            original_filename=filename,
            status="quarantined",
            uploaded_by=actor_id,
        )
    )
    # Membership must be written in the SAME transaction as the row. A document
    # with no membership rows reads as tenant-wide, so a failure between the two
    # would widen access rather than narrow it.
    memberships = department_ids if department_ids is not None else set()
    if memberships:
        await replace_document_departments(
            session,
            tenant_id=user.tenant_id,
            document_ids=[document_id],
            department_ids=memberships,
        )


async def _load_quarantined(session: AsyncSession, upload_id: uuid.UUID) -> QuarantinedDoc | None:
    """RLS scopes this to the bound tenant; foreign rows read as missing."""
    row = (
        await session.execute(
            select(
                Document.id,
                Document.tenant_id,
                Document.department_id,
                Document.original_filename,
                Document.status,
                Document.deleted_at,
                select(func.array_agg(DocumentDepartment.department_id))
                .where(DocumentDepartment.document_id == Document.id)
                .scalar_subquery()
                .label("department_ids"),
            ).where(Document.id == upload_id)
        )
    ).first()
    if row is None:
        return None
    values = list(row)
    values[-1] = frozenset(values[-1] or ())
    return QuarantinedDoc(*values)


async def _persist_version(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> uuid.UUID:
    """Blobs get-or-create + version 1 + status flip; caller owns the tx."""
    version_id = uuid.uuid4()
    await session.execute(
        insert(DocumentVersion).values(
            id=version_id,
            document_id=document_id,
            blob_sha256=None,
            version_no=1,
            created_by=actor_id,
        )
    )
    await session.execute(
        update(Document).where(Document.id == document_id).values(status="processing")
    )
    return version_id


def _enqueue_chain(document_id: uuid.UUID, version_id: uuid.UUID) -> None:
    """Hand the document to the worker pipeline; raises on any broker failure.

    The import stays inside the function so API start-up never requires the
    broker; the caller owns the failure policy (503, state stays committed).
    """
    from app.workers.tasks import process_upload_chain

    process_upload_chain.delay(str(document_id), str(version_id))


@router.post("", status_code=201, response_model=UploadIntentResponse)
async def create_upload_intent(
    request: Request,
    payload: UploadIntentRequest,
    user: UserCtx = Depends(deps.require(Action.UPLOAD)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    settings: Settings = Depends(deps.get_settings),
    storage: Storage = Depends(deps.get_storage),
) -> UploadIntentResponse:
    if payload.size_bytes > settings.upload_max_bytes:
        raise HTTPException(HTTP_413_CONTENT_TOO_LARGE, "declared size exceeds upload cap")
    document_id = uuid.uuid4()
    ttl = settings.upload_presign_ttl_seconds
    key = quarantine_key(user.tenant_id, document_id)
    async with sessions(user.tenant_id) as session:
        actor_id = await _provision_actor(session, user)
        departments = await _resolve_departments(session, user, payload.department_ids)
        await _insert_quarantine_document(
            session,
            document_id=document_id,
            user=user,
            department_ids=departments,
            filename=payload.filename,
            actor_id=actor_id,
        )
        upload = storage.presign_put(
            key,
            ttl,
            content_type=payload.content_type,
            max_bytes=settings.upload_max_bytes,
        )
        url = upload.url
        fields = upload.fields
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=document_id,
            actor_id=actor_id,
            action="upload.init",
            request=request,
        )
        await session.commit()
    return UploadIntentResponse(
        upload_id=document_id,
        presigned_put=PresignedPut(
            url=url,
            fields=fields,
            expires_at=datetime.now(tz=UTC) + timedelta(seconds=ttl),
        ),
    )


@router.post("/batch", status_code=201, response_model=BatchUploadResponse)
async def create_batch_upload_intent(
    request: Request,
    payload: BatchUploadRequest,
    user: UserCtx = Depends(deps.require(Action.UPLOAD)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    settings: Settings = Depends(deps.get_settings),
    storage: Storage = Depends(deps.get_storage),
) -> BatchUploadResponse:
    """Sign one upload per file. Caps are checked BEFORE any row is written.

    All-or-nothing at intent time: a batch that breaches a cap creates no
    document rows at all, so a rejected batch leaves nothing to reconcile.
    """
    if len(payload.files) > settings.upload_batch_max_files:
        raise HTTPException(
            HTTP_422_UNPROCESSABLE_CONTENT,
            f"batch exceeds {settings.upload_batch_max_files} files",
        )
    for f in payload.files:
        if f.size_bytes > settings.upload_max_bytes:
            raise HTTPException(HTTP_413_CONTENT_TOO_LARGE, "a file exceeds the per-file cap")
    if sum(f.size_bytes for f in payload.files) > settings.upload_batch_max_bytes:
        raise HTTPException(HTTP_413_CONTENT_TOO_LARGE, "batch exceeds the total size cap")

    batch_id = uuid.uuid4()
    ttl = settings.upload_presign_ttl_seconds
    now = datetime.now(tz=UTC)
    expires_at = now + timedelta(seconds=ttl)
    uploads: list[UploadIntentResponse] = []

    async with sessions(user.tenant_id) as session:
        actor_id = await _provision_actor(session, user)
        # Resolved once: the whole batch shares one department set, and a bad
        # set must reject the batch before any row is written.
        departments = await _resolve_departments(session, user, payload.department_ids)
        for f in payload.files:
            document_id = uuid.uuid4()
            key = quarantine_key(user.tenant_id, document_id)
            await _insert_quarantine_document(
                session,
                document_id=document_id,
                user=user,
                department_ids=departments,
                filename=f.filename,
                actor_id=actor_id,
            )
            upload = storage.presign_put(
                key,
                ttl,
                content_type=f.content_type,
                max_bytes=settings.upload_max_bytes,
            )
            await deps.record_audit(
                session,
                tenant_id=user.tenant_id,
                document_id=document_id,
                actor_id=actor_id,
                action="upload.init",
                request=request,
            )
            uploads.append(
                UploadIntentResponse(
                    upload_id=document_id,
                    presigned_put=PresignedPut(
                        url=upload.url,
                        fields=upload.fields,
                        expires_at=expires_at,
                    ),
                )
            )
        await session.commit()

    return BatchUploadResponse(
        batch_id=batch_id,
        uploads=uploads,
    )


@router.post("/{upload_id}/complete", response_model=CompleteResponse)
async def complete_upload(
    request: Request,
    upload_id: uuid.UUID,
    user: UserCtx = Depends(deps.require(Action.UPLOAD)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
    settings: Settings = Depends(deps.get_settings),
    storage: Storage = Depends(deps.get_storage),
    payload: CompleteRequest | None = None,
) -> CompleteResponse | Response:
    async with sessions(user.tenant_id) as session:
        # Authorize-BEFORE-fetch discipline (#31): RLS makes foreign rows read
        # as missing, then policy re-checks the axes server-side (#33); every
        # denial collapses into the one canonical 404 body.
        doc = await _load_quarantined(session, upload_id)
        if doc is None or doc.deleted_at is not None:
            return not_found()
        ref = DocumentRef(
            id=doc.id,
            tenant_id=doc.tenant_id,
            department_ids=doc.department_ids,
            level_rank=DEFAULT_FLOOR_RANK,
            deleted_at=doc.deleted_at,
        )
        if not can_access(user, ref, Action.UPLOAD):
            return not_found()
        if doc.status != "quarantined":
            raise HTTPException(HTTP_409_CONFLICT, "document is not quarantined")

        # #1 keeps the API off the bytes, so verify metadata only. Without this
        # a client can complete an upload it never PUT: the chain fires, the
        # worker cannot find the object, and the document strands.
        quarantine = storage.stat(quarantine_key(doc.tenant_id, doc.id))
        if quarantine is None:
            raise HTTPException(
                HTTP_409_CONFLICT, "upload did not arrive; the object was never stored"
            )
        if (
            payload is not None
            and payload.size_bytes is not None
            and quarantine.size_bytes != payload.size_bytes
        ):
            raise HTTPException(
                HTTP_409_CONFLICT,
                "stored object size does not match the declared size",
            )
        if quarantine.size_bytes > settings.upload_max_bytes:
            raise HTTPException(HTTP_413_CONTENT_TOO_LARGE, "stored object exceeds upload cap")

        actor_id = await _provision_actor(session, user)
        version_id = await _persist_version(session, document_id=doc.id, actor_id=actor_id)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=doc.id,
            actor_id=actor_id,
            action="upload.complete",
            request=request,
        )
        await session.commit()

    try:
        _enqueue_chain(doc.id, version_id)
    except Exception as exc:
        # Documented decision: committed 'processing' + 503; reconciler recovers.
        # The client is told nothing beyond "unavailable" (the broker topology is
        # not theirs to see), so the cause has to reach the operator here or it
        # reaches nobody — a 503 with no log line is undiagnosable.
        from app.workers.celery_app import celery_app

        logger.exception(
            "enqueue_failed document_id=%s version_id=%s broker=%s",
            doc.id,
            version_id,
            celery_app.conf.broker_url,
        )
        raise HTTPException(
            HTTP_503_SERVICE_UNAVAILABLE, "processing pipeline unavailable"
        ) from exc
    return CompleteResponse(document_id=doc.id, version_id=version_id, status="processing")
