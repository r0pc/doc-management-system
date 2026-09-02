# ruff: noqa: B008 -- Depends() in argument defaults is the FastAPI idiom;
# the Annotated[] form fails to resolve under CPython 3.14 PEP 649 lazy
# annotations with fastapi 0.141 (ForwardRef evaluation bug).


"""Minimal taxonomy administration (spec §3.2).

Document types are engineering-owned and get the minimal CRUD surface:
list, create (unique per parent), delete (refused while children or
classification references exist — honest 409 strings, pre-checked counts).
Security levels are POLICY-OWNED: this module exposes a READ-ONLY listing and
deliberately defines no create/update/delete route for them; the level table
is owned outside engineering per spec §3.2.

Create/delete write their audit rows in the SAME transaction as the change
(#30) via ``deps.record_audit``. Doc types are global (no tenant column in
spec §6), so no visibility axes apply here — only the MANAGE_TAXONOMY gate.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, cast

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.status import (
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from app.api import deps
from app.classification.ml.loader import embed_sample_text
from app.classification.ml.prototypes import MAX_SAMPLES, MIN_SAMPLES, compute_centroid
from app.classification.rules.configured import ConfiguredRecognizer
from app.classification.rules.safety import PatternUnsafeError, assert_pattern_safe
from app.classification.rules.validators import VALIDATORS
from app.config import Settings
from app.db.models import (
    Classification,
    DetectorRule,
    DocType,
    DocTypePrototype,
    Document,
    DocumentText,
    DocumentVersion,
    SecurityLevel,
)
from app.domain.models import Action, UserCtx
from app.extraction.registry import extract_document
from app.workers.scanning import CLAMAV_HOST, CLAMAV_PORT, ScanError, clamd_scan

settings = Settings()

router = APIRouter(prefix="/admin", tags=["admin"])


# --- wire models ---


class DocTypeOut(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    description: str


class SecurityLevelOut(BaseModel):
    id: uuid.UUID
    rank: int
    name: str
    description: str


class DocTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    parent_id: uuid.UUID | None = None
    description: str = Field(default="", max_length=1024)


class TrainPrototypeRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=MIN_SAMPLES, max_length=MAX_SAMPLES)


class TrainPrototypeResponse(BaseModel):
    doc_type_id: uuid.UUID
    sample_count: int
    dimension: int


class DocTypePrototypeOut(BaseModel):
    id: uuid.UUID
    doc_type_id: uuid.UUID
    sample_count: int
    updated_at: datetime.datetime


class DetectorRuleOut(BaseModel):
    id: uuid.UUID
    entity_type: str
    pattern: str
    validator_kind: str
    validator_config: dict[str, Any]
    context_words: list[str]
    level_rank: int
    enabled: bool


class DetectorRuleCreate(BaseModel):
    entity_type: str = Field(min_length=1, max_length=128)
    pattern: str = Field(min_length=1, max_length=512)
    validator_kind: str = Field(min_length=1, max_length=64)
    validator_config: dict[str, Any] = Field(default_factory=dict)
    context_words: list[str] = Field(min_length=1)
    level_rank: int = Field(ge=1, le=4)
    enabled: bool = True


class DetectorRuleUpdate(BaseModel):
    pattern: str | None = Field(default=None, min_length=1, max_length=512)
    validator_kind: str | None = Field(default=None, min_length=1, max_length=64)
    validator_config: dict[str, Any] | None = None
    context_words: list[str] | None = Field(default=None, min_length=1)
    level_rank: int | None = Field(default=None, ge=1, le=4)
    enabled: bool | None = None


class DetectorPreviewRequest(BaseModel):
    entity_type: str = Field(min_length=1, max_length=128)
    pattern: str = Field(min_length=1, max_length=512)
    validator_kind: str = Field(min_length=1, max_length=64)
    validator_config: dict[str, Any] = Field(default_factory=dict)
    context_words: list[str] = Field(min_length=1)
    level_rank: int = Field(ge=1, le=4)
    sample_text: str = Field(min_length=1, max_length=100000)


class DetectorMatchOut(BaseModel):
    char_start: int
    char_end: int
    score: float


class DetectorPreviewResponse(BaseModel):
    matches: list[DetectorMatchOut]


# --- data-access seams (monkeypatched in unit tests; SQL proven Wave 5) ---


async def _fetch_doc_types(session: AsyncSession) -> list[DocTypeOut]:
    rows = (
        await session.execute(
            select(DocType.id, DocType.parent_id, DocType.name, DocType.description).order_by(
                DocType.name.asc()
            )
        )
    ).all()
    return [
        DocTypeOut(id=row.id, parent_id=row.parent_id, name=row.name, description=row.description)
        for row in rows
    ]


async def _fetch_security_levels(session: AsyncSession) -> list[SecurityLevelOut]:
    rows = (
        await session.execute(
            select(
                SecurityLevel.id,
                SecurityLevel.rank,
                SecurityLevel.name,
                SecurityLevel.description,
            ).order_by(SecurityLevel.rank.asc())
        )
    ).all()
    return [
        SecurityLevelOut(id=row.id, rank=row.rank, name=row.name, description=row.description)
        for row in rows
    ]


async def _doc_type_name_conflicts(
    session: AsyncSession, name: str, parent_id: uuid.UUID | None
) -> bool:
    stmt = select(DocType.id).where(DocType.name == name)
    if parent_id is None:
        stmt = stmt.where(DocType.parent_id.is_(None))
    else:
        stmt = stmt.where(DocType.parent_id == parent_id)
    return (await session.execute(stmt)).first() is not None


async def _insert_doc_type(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    parent_id: uuid.UUID | None,
    description: str,
) -> uuid.UUID:
    doc_type_id = uuid.uuid4()
    await session.execute(
        insert(DocType).values(
            id=doc_type_id,
            tenant_id=tenant_id,
            name=name,
            parent_id=parent_id,
            description=description,
        )
    )
    return doc_type_id


async def _count_doc_type_children(session: AsyncSession, doc_type_id: uuid.UUID) -> int:
    row = (
        await session.execute(
            select(func.count()).select_from(DocType).where(DocType.parent_id == doc_type_id)
        )
    ).scalar_one()
    return int(row)


async def _count_classification_refs(session: AsyncSession, doc_type_id: uuid.UUID) -> int:
    row = (
        await session.execute(
            select(func.count())
            .select_from(Classification)
            .where(Classification.doc_type_id == doc_type_id)
        )
    ).scalar_one()
    return int(row)


async def _delete_doc_type(session: AsyncSession, doc_type_id: uuid.UUID) -> None:
    await session.execute(delete(DocType).where(DocType.id == doc_type_id))


async def _fetch_sample_embeddings(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    document_ids: list[uuid.UUID],
) -> list[list[float]]:
    stmt = (
        select(DocumentText.embedding)
        .join(DocumentVersion, DocumentVersion.id == DocumentText.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Document.tenant_id == tenant_id,
            Document.id.in_(document_ids),
            DocumentText.embedding.is_not(None),
        )
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [list(r) for r in rows if r is not None]


async def _upsert_prototype(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    doc_type_id: uuid.UUID,
    centroid: list[float],
    sample_count: int,
) -> None:
    stmt = (
        pg_insert(DocTypePrototype)
        .values(
            tenant_id=tenant_id,
            doc_type_id=doc_type_id,
            centroid_vector=centroid,
            sample_count=sample_count,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "doc_type_id"],
            set_={
                "centroid_vector": centroid,
                "sample_count": sample_count,
                "updated_at": func.now(),
            },
        )
    )
    await session.execute(stmt)


async def _delete_prototype(
    session: AsyncSession, *, tenant_id: uuid.UUID, doc_type_id: uuid.UUID
) -> int:
    stmt = delete(DocTypePrototype).where(
        DocTypePrototype.tenant_id == tenant_id,
        DocTypePrototype.doc_type_id == doc_type_id,
    )
    res = await session.execute(stmt)
    return int(cast("CursorResult[Any]", res).rowcount or 0)


async def _delete_all_prototypes(session: AsyncSession, *, tenant_id: uuid.UUID) -> int:
    stmt = delete(DocTypePrototype).where(DocTypePrototype.tenant_id == tenant_id)
    res = await session.execute(stmt)
    return int(cast("CursorResult[Any]", res).rowcount or 0)


async def _fetch_prototypes(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[DocTypePrototypeOut]:
    rows = (
        await session.execute(
            select(
                DocTypePrototype.id,
                DocTypePrototype.doc_type_id,
                DocTypePrototype.sample_count,
                DocTypePrototype.updated_at,
            )
            .where(DocTypePrototype.tenant_id == tenant_id)
            .order_by(DocTypePrototype.updated_at.desc())
        )
    ).all()
    return [
        DocTypePrototypeOut(
            id=r.id,
            doc_type_id=r.doc_type_id,
            sample_count=r.sample_count,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


async def _fetch_detector_rules(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[DetectorRuleOut]:
    rows = (
        await session.execute(
            select(
                DetectorRule.id,
                DetectorRule.entity_type,
                DetectorRule.pattern,
                DetectorRule.validator_kind,
                DetectorRule.validator_config,
                DetectorRule.context_words,
                DetectorRule.level_rank,
                DetectorRule.enabled,
            )
            .where(DetectorRule.tenant_id == tenant_id)
            .order_by(DetectorRule.entity_type.asc())
        )
    ).all()
    return [
        DetectorRuleOut(
            id=r.id,
            entity_type=r.entity_type,
            pattern=r.pattern,
            validator_kind=r.validator_kind,
            validator_config=r.validator_config,
            context_words=list(r.context_words),
            level_rank=r.level_rank,
            enabled=r.enabled,
        )
        for r in rows
    ]


async def _insert_detector_rule(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    payload: DetectorRuleCreate,
) -> DetectorRuleOut:
    rule_id = uuid.uuid4()
    row = DetectorRule(
        id=rule_id,
        tenant_id=tenant_id,
        entity_type=payload.entity_type,
        pattern=payload.pattern,
        validator_kind=payload.validator_kind,
        validator_config=payload.validator_config,
        context_words=payload.context_words,
        level_rank=payload.level_rank,
        enabled=payload.enabled,
    )
    session.add(row)
    await session.flush()
    return DetectorRuleOut(
        id=rule_id,
        entity_type=payload.entity_type,
        pattern=payload.pattern,
        validator_kind=payload.validator_kind,
        validator_config=payload.validator_config,
        context_words=payload.context_words,
        level_rank=payload.level_rank,
        enabled=payload.enabled,
    )


async def _update_detector_rule(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: DetectorRuleUpdate,
) -> DetectorRuleOut | None:
    row = (
        await session.execute(
            select(DetectorRule).where(
                DetectorRule.id == rule_id, DetectorRule.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if payload.pattern is not None:
        row.pattern = payload.pattern
    if payload.validator_kind is not None:
        row.validator_kind = payload.validator_kind
    if payload.validator_config is not None:
        row.validator_config = payload.validator_config
    if payload.context_words is not None:
        row.context_words = payload.context_words
    if payload.level_rank is not None:
        row.level_rank = payload.level_rank
    if payload.enabled is not None:
        row.enabled = payload.enabled
    await session.flush()
    return DetectorRuleOut(
        id=row.id,
        entity_type=row.entity_type,
        pattern=row.pattern,
        validator_kind=row.validator_kind,
        validator_config=row.validator_config,
        context_words=list(row.context_words),
        level_rank=row.level_rank,
        enabled=row.enabled,
    )


async def _delete_detector_rule(
    session: AsyncSession, *, tenant_id: uuid.UUID, rule_id: uuid.UUID
) -> bool:
    res = await session.execute(
        delete(DetectorRule).where(DetectorRule.id == rule_id, DetectorRule.tenant_id == tenant_id)
    )
    return (cast(CursorResult[Any], res).rowcount or 0) > 0


# --- handlers ---


@router.get("/doc-types", response_model=list[DocTypeOut])
async def list_doc_types(
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> list[DocTypeOut]:
    async with sessions(user.tenant_id) as session:
        return await _fetch_doc_types(session)


@router.post("/doc-types", status_code=201, response_model=DocTypeOut)
async def create_doc_type(
    request: Request,
    payload: DocTypeCreate,
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> DocTypeOut:
    async with sessions(user.tenant_id) as session:
        if await _doc_type_name_conflicts(session, payload.name, payload.parent_id):
            raise HTTPException(
                HTTP_409_CONFLICT, "document type name already exists under this parent"
            )
        doc_type_id = await _insert_doc_type(
            session,
            tenant_id=user.tenant_id,
            name=payload.name,
            parent_id=payload.parent_id,
            description=payload.description,
        )
        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=None,
            actor_id=actor_id,
            action="taxonomy.create",
            request=request,
        )
        await session.commit()
    return DocTypeOut(
        id=doc_type_id,
        parent_id=payload.parent_id,
        name=payload.name,
        description=payload.description,
    )


@router.delete("/doc-types/{doc_type_id}", status_code=204)
async def remove_doc_type(
    request: Request,
    doc_type_id: uuid.UUID,
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> Response:
    async with sessions(user.tenant_id) as session:
        children = await _count_doc_type_children(session, doc_type_id)
        if children > 0:
            raise HTTPException(HTTP_409_CONFLICT, "document type has child types")
        references = await _count_classification_refs(session, doc_type_id)
        if references > 0:
            raise HTTPException(HTTP_409_CONFLICT, "document type is referenced by classifications")
        await _delete_doc_type(session, doc_type_id)
        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=None,
            actor_id=actor_id,
            action="taxonomy.delete",
            request=request,
        )
        await session.commit()
    return Response(status_code=204)


@router.post("/doc-types/{doc_type_id}/prototype", response_model=TrainPrototypeResponse)
async def train_doc_type_prototype(
    request: Request,
    doc_type_id: uuid.UUID,
    payload: TrainPrototypeRequest,
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> TrainPrototypeResponse:
    async with sessions(user.tenant_id) as session:
        embeddings = await _fetch_sample_embeddings(session, user.tenant_id, payload.document_ids)
        if len(embeddings) < len(payload.document_ids):
            raise HTTPException(HTTP_409_CONFLICT, "one or more documents have no stored embedding")
        try:
            centroid = compute_centroid(embeddings)
        except ValueError as err:
            raise HTTPException(HTTP_409_CONFLICT, str(err)) from err

        await _upsert_prototype(
            session,
            tenant_id=user.tenant_id,
            doc_type_id=doc_type_id,
            centroid=centroid,
            sample_count=len(payload.document_ids),
        )
        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=None,
            actor_id=actor_id,
            action="prototype.train",
            request=request,
            detail=f"doc_type_id={doc_type_id},sample_count={len(payload.document_ids)}",
        )
        await session.commit()

    return TrainPrototypeResponse(
        doc_type_id=doc_type_id,
        sample_count=len(payload.document_ids),
        dimension=len(centroid),
    )


@router.post("/doc-types/{doc_type_id}/prototype-upload", response_model=TrainPrototypeResponse)
async def train_doc_type_prototype_upload(
    request: Request,
    doc_type_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> TrainPrototypeResponse:
    """Train a prototype vector from directly uploaded sample files.

    Scans for malware, extracts text, and computes sentence-transformer embeddings
    purely in memory to compute the centroid. Uploaded files are NEVER saved to
    storage or recorded in repository document tables.
    """
    if len(files) < MIN_SAMPLES:
        raise HTTPException(
            HTTP_422_UNPROCESSABLE_ENTITY,
            f"need at least {MIN_SAMPLES} sample files, got {len(files)}",
        )
    if len(files) > MAX_SAMPLES:
        raise HTTPException(
            HTTP_422_UNPROCESSABLE_ENTITY,
            f"maximum {MAX_SAMPLES} sample files allowed, got {len(files)}",
        )

    embeddings: list[list[float]] = []
    for file in files:
        data = await file.read()
        if not data:
            raise HTTPException(
                HTTP_422_UNPROCESSABLE_ENTITY,
                f"Sample file '{file.filename or 'unnamed'}' is empty",
            )
        # 1. Malware scan
        try:
            verdict = clamd_scan(CLAMAV_HOST, CLAMAV_PORT, data)
            if not verdict.clean:
                raise HTTPException(
                    HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Malware detected in sample '{file.filename}': {verdict.signature}",
                )
        except ScanError as exc:
            if settings.env == "dev":
                pass
            else:
                raise HTTPException(
                    HTTP_503_SERVICE_UNAVAILABLE,
                    "Malware scanning service is temporarily unavailable",
                ) from exc

        # 2. Text extraction
        try:
            extracted = extract_document(data)
        except Exception as exc:
            raise HTTPException(
                HTTP_422_UNPROCESSABLE_ENTITY,
                f"Failed to extract text from '{file.filename}': {exc}",
            ) from exc

        if not extracted.text or not extracted.text.strip():
            raise HTTPException(
                HTTP_422_UNPROCESSABLE_ENTITY,
                f"Sample file '{file.filename}' contains no extractable text",
            )

        # 3. Embedding
        vector = embed_sample_text(extracted.text)
        if vector is None:
            raise HTTPException(
                HTTP_503_SERVICE_UNAVAILABLE,
                f"Embedding model unavailable for sample '{file.filename}'",
            )
        embeddings.append(vector)

    # 4. Centroid
    try:
        centroid = compute_centroid(embeddings)
    except ValueError as err:
        raise HTTPException(HTTP_422_UNPROCESSABLE_ENTITY, str(err)) from err

    # 5. Persist prototype & audit log (no documents/blobs saved)
    async with sessions(user.tenant_id) as session:
        doc_type_exists = (
            await session.execute(select(DocType.id).where(DocType.id == doc_type_id))
        ).scalar_one_or_none()
        if doc_type_exists is None:
            raise HTTPException(HTTP_404_NOT_FOUND, "document type not found")

        await _upsert_prototype(
            session,
            tenant_id=user.tenant_id,
            doc_type_id=doc_type_id,
            centroid=centroid,
            sample_count=len(files),
        )
        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=None,
            actor_id=actor_id,
            action="prototype.train",
            request=request,
            detail=f"doc_type_id={doc_type_id},sample_count={len(files)},source=direct_upload",
        )
        await session.commit()

    return TrainPrototypeResponse(
        doc_type_id=doc_type_id,
        sample_count=len(files),
        dimension=len(centroid),
    )


@router.get("/prototypes", response_model=list[DocTypePrototypeOut])
async def list_prototypes(
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> list[DocTypePrototypeOut]:
    """List all trained document type prototypes for the tenant."""
    async with sessions(user.tenant_id) as session:
        return await _fetch_prototypes(session, user.tenant_id)


@router.delete("/doc-types/{doc_type_id}/prototype", status_code=204)
async def reset_doc_type_prototype(
    request: Request,
    doc_type_id: uuid.UUID,
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> Response:
    """Reset / delete a trained prototype vector for a specific document type."""
    async with sessions(user.tenant_id) as session:
        deleted = await _delete_prototype(
            session, tenant_id=user.tenant_id, doc_type_id=doc_type_id
        )
        if deleted > 0:
            actor_id = await deps.provision_actor(session, user)
            await deps.record_audit(
                session,
                tenant_id=user.tenant_id,
                document_id=None,
                actor_id=actor_id,
                action="prototype.reset",
                request=request,
                detail=f"doc_type_id={doc_type_id}",
            )
            await session.commit()
    return Response(status_code=204)


@router.delete("/prototypes", status_code=204)
async def reset_all_prototypes(
    request: Request,
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> Response:
    """Reset / delete all trained prototype vectors for the tenant."""
    async with sessions(user.tenant_id) as session:
        deleted = await _delete_all_prototypes(session, tenant_id=user.tenant_id)
        if deleted > 0:
            actor_id = await deps.provision_actor(session, user)
            await deps.record_audit(
                session,
                tenant_id=user.tenant_id,
                document_id=None,
                actor_id=actor_id,
                action="prototype.reset_all",
                request=request,
                detail=f"deleted_count={deleted}",
            )
            await session.commit()
    return Response(status_code=204)


@router.get("/security-levels", response_model=list[SecurityLevelOut])
async def list_security_levels(
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> list[SecurityLevelOut]:
    """READ-ONLY by design: levels are policy-owned (spec §3.2); no CUD routes."""
    async with sessions(user.tenant_id) as session:
        return await _fetch_security_levels(session)


@router.get("/detectors", response_model=list[DetectorRuleOut])
async def list_detectors(
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> list[DetectorRuleOut]:
    async with sessions(user.tenant_id) as session:
        return await _fetch_detector_rules(session, user.tenant_id)


@router.post("/detectors", response_model=DetectorRuleOut, status_code=201)
async def create_detector(
    request: Request,
    payload: DetectorRuleCreate,
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> DetectorRuleOut:
    try:
        assert_pattern_safe(payload.pattern)
    except PatternUnsafeError as err:
        raise HTTPException(status_code=422, detail=f"Pattern unsafe or invalid: {err}") from err

    if payload.validator_kind not in VALIDATORS:
        raise HTTPException(
            status_code=422, detail=f"Unknown validator_kind: {payload.validator_kind}"
        )

    async with sessions(user.tenant_id) as session:
        rule = await _insert_detector_rule(session, tenant_id=user.tenant_id, payload=payload)
        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=None,
            actor_id=actor_id,
            action="detector.create",
            request=request,
            detail=f"entity_type={payload.entity_type},rule_id={rule.id}",
        )
        await session.commit()
    return rule


@router.patch("/detectors/{detector_id}", response_model=DetectorRuleOut)
async def update_detector(
    request: Request,
    detector_id: uuid.UUID,
    payload: DetectorRuleUpdate,
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> DetectorRuleOut:
    if payload.pattern is not None:
        try:
            assert_pattern_safe(payload.pattern)
        except PatternUnsafeError as err:
            raise HTTPException(
                status_code=422, detail=f"Pattern unsafe or invalid: {err}"
            ) from err

    if payload.validator_kind is not None and payload.validator_kind not in VALIDATORS:
        raise HTTPException(
            status_code=422, detail=f"Unknown validator_kind: {payload.validator_kind}"
        )

    async with sessions(user.tenant_id) as session:
        rule = await _update_detector_rule(
            session, tenant_id=user.tenant_id, rule_id=detector_id, payload=payload
        )
        if rule is None:
            raise HTTPException(status_code=404, detail="Detector rule not found")
        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=None,
            actor_id=actor_id,
            action="detector.update",
            request=request,
            detail=f"rule_id={detector_id}",
        )
        await session.commit()
    return rule


@router.delete("/detectors/{detector_id}", status_code=204)
async def remove_detector(
    request: Request,
    detector_id: uuid.UUID,
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> Response:
    async with sessions(user.tenant_id) as session:
        deleted = await _delete_detector_rule(
            session, tenant_id=user.tenant_id, rule_id=detector_id
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Detector rule not found")
        actor_id = await deps.provision_actor(session, user)
        await deps.record_audit(
            session,
            tenant_id=user.tenant_id,
            document_id=None,
            actor_id=actor_id,
            action="detector.delete",
            request=request,
            detail=f"rule_id={detector_id}",
        )
        await session.commit()
    return Response(status_code=204)


@router.post("/detectors/preview", response_model=DetectorPreviewResponse)
async def preview_detector(
    payload: DetectorPreviewRequest,
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
) -> DetectorPreviewResponse:
    try:
        assert_pattern_safe(payload.pattern)
    except PatternUnsafeError as err:
        raise HTTPException(status_code=422, detail=f"Pattern unsafe or invalid: {err}") from err

    if payload.validator_kind not in VALIDATORS:
        raise HTTPException(
            status_code=422, detail=f"Unknown validator_kind: {payload.validator_kind}"
        )

    recognizer = ConfiguredRecognizer(
        entity_type=payload.entity_type,
        pattern=payload.pattern,
        context_words=payload.context_words,
        validator_kind=payload.validator_kind,
        validator_config=payload.validator_config,
    )
    findings = recognizer.scan(payload.sample_text)
    # Return character offsets and scores only — never matched text (#12)
    return DetectorPreviewResponse(
        matches=[
            DetectorMatchOut(
                char_start=f.char_start,
                char_end=f.char_end,
                score=f.score,
            )
            for f in findings
        ]
    )
