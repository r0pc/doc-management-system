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

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.status import HTTP_409_CONFLICT

from app.api import deps
from app.classification.ml.prototypes import MAX_SAMPLES, MIN_SAMPLES, compute_centroid
from app.db.models import (
    Classification,
    DocType,
    DocTypePrototype,
    Document,
    DocumentText,
    DocumentVersion,
    SecurityLevel,
)
from app.domain.models import Action, UserCtx

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
    session: AsyncSession, *, name: str, parent_id: uuid.UUID | None, description: str
) -> uuid.UUID:
    doc_type_id = uuid.uuid4()
    await session.execute(
        insert(DocType).values(
            id=doc_type_id, name=name, parent_id=parent_id, description=description
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


@router.get("/security-levels", response_model=list[SecurityLevelOut])
async def list_security_levels(
    user: UserCtx = Depends(deps.require(Action.MANAGE_TAXONOMY)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> list[SecurityLevelOut]:
    """READ-ONLY by design: levels are policy-owned (spec §3.2); no CUD routes."""
    async with sessions(user.tenant_id) as session:
        return await _fetch_security_levels(session)
