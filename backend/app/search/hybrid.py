"""Reciprocal-rank fusion and the search orchestrator (#29).

Pure fusion math first: :func:`rrf_merge` is a pure function unit-tested
against hand-computed truth tables (k=60, contribution 1/(k+rank) per arm hit,
deterministic tie-breaking). Scores are summed across arms; raw relevance
scores from different arms are never compared (#29).

Divergence from spec §4.2 SQL (documented decision): the spec sketches one
statement fusing both arms via SUM(1/(60+r)) over UNION ALL. Phase 1 executes
each arm separately (two round-trips are acceptable at this scale) and fuses
in Python via rrf_merge — the same RRF math with identical k=60, fully
unit-tested, avoiding fragile cross-dialect window plumbing until the vector
arm activates. Revisit when embeddings go live.

Facets and snippets derive ONLY from the already-filtered candidate set (#28):
facet statements GROUP BY over the same candidates subquery the arms select
from, and snippets are generated exclusively for fused results.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, Subquery, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import LevelName, UserCtx
from app.search.filters import (
    build_visible_candidates,
    compose_keyword_subquery,
    compose_vector_subquery,
)

RRF_K = 60
DEFAULT_LIMIT = 20
SNIPPET_RADIUS = 120
SNIPPET_MAX_CHARS = 280
FACET_NULL_KEY = "unknown"


@dataclass(frozen=True, slots=True)
class VersionHit:
    """One arm's placement of one version (1-based rank assigned by SQL)."""

    version_id: uuid.UUID
    document_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class FusedHit:
    hit: VersionHit
    score: float


@dataclass(frozen=True, slots=True)
class ResultMeta:
    """Display metadata for one fused version, loaded FROM the candidate set."""

    filename: str
    level: str | None
    doc_type: str | None


@dataclass(frozen=True, slots=True)
class FusedResult:
    version_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    level: str | None
    doc_type: str | None
    snippet: str
    score: float


@dataclass(frozen=True, slots=True)
class SearchResult:
    items: list[FusedResult]
    level_facets: dict[str, int]
    doc_type_facets: dict[str, int]
    total_candidates: int


def rrf_merge(
    keyword_ranked: Sequence[VersionHit],
    vector_ranked: Sequence[VersionHit],
    k: int = RRF_K,
    limit: int = DEFAULT_LIMIT,
) -> list[FusedHit]:
    """Sum 1/(k+rank) per arm over versions; deterministic ordering.

    Ties break on higher combined arm count, then lexicographic version_id.
    (With pure positive contributions an equal score implies an equal count,
    so the count tier is spec-pinned defence, exercised only if contribution
    rules ever change.)
    """
    scores: dict[uuid.UUID, float] = {}
    hits: dict[uuid.UUID, VersionHit] = {}
    arms: dict[uuid.UUID, int] = {}
    for ranked in (keyword_ranked, vector_ranked):
        for rank, hit in enumerate(ranked, start=1):
            scores[hit.version_id] = scores.get(hit.version_id, 0.0) + 1 / (k + rank)
            hits.setdefault(hit.version_id, hit)
            arms[hit.version_id] = arms.get(hit.version_id, 0) + 1
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], -arms[kv[0]], str(kv[0])))
    return [FusedHit(hit=hits[version_id], score=score) for version_id, score in ordered[:limit]]


def snippet_for(version_id: uuid.UUID, text: str, q: str, radius: int = SNIPPET_RADIUS) -> str:
    """First-match window of ±radius chars around the earliest query term.

    Ellipses mark truncation either side; output never exceeds
    SNIPPET_MAX_CHARS. Absent terms fall back to the leading text. Pure:
    ``version_id`` rides along for caller-side correlation only.
    """
    if not text:
        return ""
    lowered = text.lower()
    positions = [lowered.find(term) for term in q.lower().split() if term]
    found = [pos for pos in positions if pos >= 0]
    if found:
        pos = min(found)
        start = max(0, pos - radius)
        end = min(len(text), pos + radius)
    else:
        start, end = 0, min(len(text), 2 * radius)
    end = min(end, start + SNIPPET_MAX_CHARS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


# --- data-access seams (monkeypatched in endpoint tests) ---


async def _run_keyword_arm(session: AsyncSession, stmt: Select[Any]) -> Sequence[Any]:
    return (await session.execute(stmt)).all()


async def _run_vector_arm(session: AsyncSession, stmt: Select[Any]) -> Sequence[Any]:
    return (await session.execute(stmt)).all()


async def _load_result_documents(
    session: AsyncSession, candidates: Subquery, version_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, ResultMeta]:
    """Metadata for fused results, selected THROUGH the candidate set so no
    hidden row's metadata can ever be resolved (#27 by construction)."""
    if not version_ids:
        return {}
    stmt = select(
        candidates.c.version_id,
        candidates.c.filename,
        candidates.c.level_name,
        candidates.c.doc_type_name,
    ).where(candidates.c.version_id.in_(version_ids))
    rows = (await session.execute(stmt)).all()
    return {
        row.version_id: ResultMeta(
            filename=row.filename, level=row.level_name, doc_type=row.doc_type_name
        )
        for row in rows
    }


async def _load_snippet_text(
    session: AsyncSession, version_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Snippet source text. Raw document text is not persisted this wave (the
    schema stores tsv/embeddings/char_count only), so this returns {} until
    the derived-text store lands; snippet plumbing is exercised via fakes."""
    return {}


async def _run_group_counts(session: AsyncSession, stmt: Select[Any]) -> Sequence[Any]:
    return (await session.execute(stmt)).all()


# --- facets (#28): GROUP BY over THE SAME filtered candidate set ---


async def facet_counts(session: AsyncSession, candidates: Subquery) -> dict[str, int]:
    """Security-level distribution of the visible candidate corpus."""
    return await _grouped_counts(session, candidates.c.level_name)


async def doc_type_facet_counts(session: AsyncSession, candidates: Subquery) -> dict[str, int]:
    """Document-type distribution of the visible candidate corpus."""
    return await _grouped_counts(session, candidates.c.doc_type_name)


async def _grouped_counts(session: AsyncSession, column: Any) -> dict[str, int]:
    stmt = select(column, func.count()).group_by(column)
    rows = await _run_group_counts(session, stmt)
    return {(name if name is not None else FACET_NULL_KEY): int(count) for name, count in rows}


# --- orchestrator ---


def _to_hit(row: Any) -> VersionHit:
    return VersionHit(version_id=row.version_id, document_id=row.document_id)


async def search_documents(
    session: AsyncSession,
    user: UserCtx,
    q: str,
    *,
    limit: int = DEFAULT_LIMIT,
    level: LevelName | None = None,
    doc_type: str | None = None,
) -> SearchResult:
    """Execute both arms over the caller's filtered candidates, fuse via RRF.

    Every downstream artifact — results, metadata, facets, totals — derives
    from the ONE filtered candidate set (#27/#28); nothing is filtered after
    fusion.
    """
    candidates_stmt = build_visible_candidates(user, level=level, doc_type=doc_type)
    candidates = candidates_stmt.subquery(name="candidates")
    keyword_rows = await _run_keyword_arm(session, compose_keyword_subquery(candidates, q))
    vector_rows = await _run_vector_arm(session, compose_vector_subquery(candidates))
    fused = rrf_merge(
        [_to_hit(row) for row in keyword_rows],
        [_to_hit(row) for row in vector_rows],
        limit=limit,
    )
    version_ids = [fused_hit.hit.version_id for fused_hit in fused]
    meta = await _load_result_documents(session, candidates, version_ids)
    texts = await _load_snippet_text(session, version_ids)
    items = [
        FusedResult(
            version_id=fused_hit.hit.version_id,
            document_id=fused_hit.hit.document_id,
            filename=meta[fused_hit.hit.version_id].filename,
            level=meta[fused_hit.hit.version_id].level,
            doc_type=meta[fused_hit.hit.version_id].doc_type,
            snippet=snippet_for(
                fused_hit.hit.version_id, texts.get(fused_hit.hit.version_id, ""), q
            ),
            score=fused_hit.score,
        )
        for fused_hit in fused
    ]
    level_facets = await facet_counts(session, candidates)
    doc_type_facets = await doc_type_facet_counts(session, candidates)
    # Every candidate lands in exactly one level group, so the sum IS the
    # visible-corpus size — information about what the caller can see only (#28).
    return SearchResult(
        items=items,
        level_facets=level_facets,
        doc_type_facets=doc_type_facets,
        total_candidates=sum(level_facets.values()),
    )
