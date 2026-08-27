# ruff: noqa: B008 -- Depends() in argument defaults is the FastAPI idiom;
# the Annotated[] form fails to resolve under CPython 3.14 PEP 649 lazy
# annotations with fastapi 0.141 (ForwardRef evaluation bug).


"""Upload endpoints: presigned intent + completion (invariants #1, #3, #5, #19).

Flow: ``POST /v1/uploads`` records intent — a ``quarantined`` documents row
plus a presigned PUT for the browser to hit object storage directly; the API
never touches bytes on the write path (#1). ``POST /v1/uploads/{id}/complete``
reads the quarantined bytes ONCE, re-checks the declared size, sniffs the MIME
type from content alone (#19 — extensions are never trusted), hashes sha256,
promotes the blob into the immutable primary bucket (#16, dedup on equal
bytes), records version 1 and flips status to ``processing``, then enqueues
the worker chain.

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

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from starlette.status import (
    HTTP_409_CONFLICT,
    HTTP_413_CONTENT_TOO_LARGE,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from app.api import deps
from app.api.v1.errors import not_found
from app.config import Settings
from app.db.models import Blob, Document, DocumentVersion
from app.domain.models import DEFAULT_FLOOR_RANK, Action, DocumentRef, UserCtx
from app.domain.policy import can_access
from app.extraction.registry import get_handler
from app.extraction.sniff import sniff_mime
from app.storage.base import Storage, clamp_presign_ttl
from app.storage.keys import primary_key, quarantine_key

# allow: SIZE_OK - single upload resource surface (2 endpoints + ingest
# helpers); the file whitelist for this wave forbids new modules. The
# _ingest/_persist seams move into db/repositories when that package
# expands (Wave 5), which brings this file back under the ceiling.
router = APIRouter(prefix="/uploads", tags=["uploads"])


class UploadIntentRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(ge=1)
    content_type: str = Field(min_length=1)


class CompleteRequest(BaseModel):
    size_bytes: int | None = Field(default=None, ge=1)


class PresignedPut(BaseModel):
    url: str
    expires_at: datetime


class UploadIntentResponse(BaseModel):
    upload_id: uuid.UUID
    presigned_put: PresignedPut


class CompleteResponse(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    status: str


@dataclass(frozen=True, slots=True)
class QuarantinedDoc:
    """Minimal projection of a documents row at completion time."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    department_id: uuid.UUID | None
    original_filename: str
    status: str
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of the single read over quarantined bytes."""

    sha256: str
    size_bytes: int
    mime: str
    object_key: str


async def _provision_actor(session: AsyncSession, user: UserCtx) -> uuid.UUID:
    return await deps.provision_actor(session, user)


async def _insert_quarantine_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    user: UserCtx,
    filename: str,
    actor_id: uuid.UUID,
) -> None:
    await session.execute(
        insert(Document).values(
            id=document_id,
            tenant_id=user.tenant_id,
            department_id=user.department_id,
            original_filename=filename,
            status="quarantined",
            uploaded_by=actor_id,
        )
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
            ).where(Document.id == upload_id)
        )
    ).first()
    if row is None:
        return None
    return QuarantinedDoc(*row)


def _ingest_bytes(
    storage: Storage,
    key: str,
    *,
    declared_size: int | None,
    max_bytes: int,
    tenant_id: uuid.UUID,
) -> IngestResult:
    """Single pass over quarantined bytes: verify, sniff, hash, promote (#19/#16)."""
    with storage.open(key) as handle:
        data: bytes = handle.read()
    actual = len(data)
    if actual > max_bytes or (declared_size is not None and actual != declared_size):
        raise HTTPException(HTTP_413_CONTENT_TOO_LARGE, "payload fails size verification")
    mime = sniff_mime(data)  # UnknownMimeError -> 422 envelope
    get_handler(mime)  # UnsupportedMimeError -> 422 envelope
    digest = hashlib.sha256(data).hexdigest()
    object_key = primary_key(tenant_id, digest)
    storage.put(object_key, BytesIO(data), content_type=mime)
    return IngestResult(sha256=digest, size_bytes=actual, mime=mime, object_key=object_key)


async def _persist_ingest(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    result: IngestResult,
) -> uuid.UUID:
    """Blobs get-or-create + version 1 + status flip; caller owns the tx."""
    existing = await session.execute(select(Blob.sha256).where(Blob.sha256 == result.sha256))
    if existing.scalar_one_or_none() is None:
        await session.execute(
            insert(Blob).values(
                sha256=result.sha256,
                size_bytes=result.size_bytes,
                mime_sniffed=result.mime,
                bucket_key=result.object_key,
            )
        )
    version_id = uuid.uuid4()
    await session.execute(
        insert(DocumentVersion).values(
            id=version_id,
            document_id=document_id,
            blob_sha256=result.sha256,
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
    ttl = clamp_presign_ttl(settings.presign_ttl_seconds)
    key = quarantine_key(user.tenant_id, document_id)
    async with sessions(user.tenant_id) as session:
        actor_id = await _provision_actor(session, user)
        await _insert_quarantine_document(
            session,
            document_id=document_id,
            user=user,
            filename=payload.filename,
            actor_id=actor_id,
        )
        # S3 backends expose a real presigned PUT; local dev falls back to
        # its HMAC GET URL (single call site - inlined by the one-off rule).
        presign_put = getattr(storage, "presign_put", None)
        if callable(presign_put):
            url: str = presign_put(key, ttl, content_type=payload.content_type)
        else:
            url = storage.presign(key, ttl, filename=payload.filename)
        await deps.record_audit(
            session,
            document_id=document_id,
            actor_id=actor_id,
            action="upload.init",
            request=request,
        )
        await session.commit()
    return UploadIntentResponse(
        upload_id=document_id,
        presigned_put=PresignedPut(
            url=url, expires_at=datetime.now(tz=UTC) + timedelta(seconds=ttl)
        ),
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
    declared = payload.size_bytes if payload is not None else None
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
            department_id=doc.department_id,
            level_rank=DEFAULT_FLOOR_RANK,
            deleted_at=doc.deleted_at,
        )
        if not can_access(user, ref, Action.UPLOAD):
            return not_found()
        if doc.status != "quarantined":
            raise HTTPException(HTTP_409_CONFLICT, "document is not quarantined")

        actor_id = await _provision_actor(session, user)
        quarantine = quarantine_key(user.tenant_id, upload_id)
        result = await run_in_threadpool(
            _ingest_bytes,
            storage,
            quarantine,
            declared_size=declared,
            max_bytes=settings.upload_max_bytes,
            tenant_id=user.tenant_id,
        )
        version_id = await _persist_ingest(
            session, document_id=doc.id, actor_id=actor_id, result=result
        )
        await deps.record_audit(
            session,
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
        raise HTTPException(
            HTTP_503_SERVICE_UNAVAILABLE, "processing pipeline unavailable"
        ) from exc
    return CompleteResponse(document_id=doc.id, version_id=version_id, status="processing")
