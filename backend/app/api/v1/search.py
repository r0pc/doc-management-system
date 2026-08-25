# ruff: noqa: B008 -- Depends() in argument defaults is the FastAPI idiom;
# the Annotated[] form fails to resolve under CPython 3.14 PEP 649 lazy
# annotations with fastapi 0.141 (ForwardRef evaluation bug).


"""GET /v1/search: hybrid keyword+vector search over visible documents.

Authorization: require(VIEW) server-side; visibility itself is enforced INSIDE
the candidate SQL (see app.search.filters), so response page length, facets
and totals describe only what the caller may see (#27/#28).

Pagination honesty: NO cursor on this endpoint. Cursor pagination needs a
stable sort key; fused RRF ranks change with the corpus, so a cursor anchored
on (score, version_id) can skip or duplicate across requests. OFFSET is banned
by #32, so this endpoint ships limit-only and stable-key pagination is flagged
for the Wave 5 decision rather than faked with an unstable key.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api import deps
from app.domain.models import Action, LevelName, UserCtx
from app.search import hybrid

router = APIRouter(prefix="/search", tags=["search"])

DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 50


class SearchHit(BaseModel):
    version_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    level: str | None
    doc_type: str | None
    snippet: str
    score: float


class Facets(BaseModel):
    levels: dict[str, int]
    doc_types: dict[str, int]


class SearchResponse(BaseModel):
    results: list[SearchHit]
    facets: Facets
    total_candidates: int


@router.get("", response_model=SearchResponse)
async def search(
    q: str = Query(...),
    limit: int = Query(default=DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT),
    level: LevelName | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    user: UserCtx = Depends(deps.require(Action.VIEW)),
    sessions: deps.TenantSessionOpener = Depends(deps.get_tenant_sessions),
) -> SearchResponse:
    query = q.strip()
    if not query:
        raise HTTPException(400, "q must not be empty")
    async with sessions(user.tenant_id) as session:
        result = await hybrid.search_documents(
            session, user, query, limit=limit, level=level, doc_type=doc_type
        )
    return SearchResponse(
        results=[
            SearchHit(
                version_id=item.version_id,
                document_id=item.document_id,
                filename=item.filename,
                level=item.level,
                doc_type=item.doc_type,
                snippet=item.snippet,
                score=item.score,
            )
            for item in result.items
        ],
        facets=Facets(levels=result.level_facets, doc_types=result.doc_type_facets),
        total_candidates=result.total_candidates,
    )
