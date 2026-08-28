"""Visibility-filtered candidate sets and the two ranking arms (#27).

THE structural guarantee: every search arm selects FROM the candidate subquery
built by :func:`build_visible_candidates`, so the two-axis visibility
predicate (#25: clearance rank x department subtree) is composed INTO the arms
by construction — it cannot be forgotten, and it cannot be applied after
ranking or fusion. Post-hoc filtering of a fused result set leaks through page
length and hit counts (#27); no ``WHERE`` exists downstream of these composers.

Current-version semantics: search operates on ``document_text``, keyed by
version_id; only the CURRENT classified version (the row
``documents.current_classification_id`` points at) carries indexed text, so
candidates join classifications through the pointer and document_text through
``classification.version_id`` (#21). Documents without indexed text on their
current version are simply not searchable yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, Subquery, false, func, or_, select

from app.db.models import Classification, DocType, Document, DocumentText, SecurityLevel
from app.domain.models import DEFAULT_FLOOR_RANK, LevelName, UserCtx

KEYWORD_ARM_LIMIT = 100
VECTOR_ARM_LIMIT = 100


def build_visible_candidates(
    user: UserCtx, *, level: LevelName | None = None, doc_type: str | None = None
) -> Select[Any]:
    """Version-scoped candidate rows the caller may ever see.

    Both access axes live in this single WHERE (#25): clearance rank via the
    COALESCE'd security_levels.rank (unlabelled falls UP to the Internal floor,
    #9), department subtree via the NULL-or-whitelist predicate. Optional
    level/doc_type facets filters are applied HERE too, so facet counts stay
    consistent with results by construction (#28).
    """
    stmt = (
        select(
            Document.id.label("document_id"),
            DocumentText.version_id.label("version_id"),
            Document.original_filename.label("filename"),
            SecurityLevel.name.label("level_name"),
            DocType.name.label("doc_type_name"),
            DocumentText.tsv.label("tsv"),
            # Both ranking signals are projected into the ONE filtered set, so
            # neither arm has to reach past it to a raw table to rank (#27).
            DocumentText.embedding.label("embedding"),
        )
        .join(Classification, Document.current_classification_id == Classification.id)
        .join(DocumentText, DocumentText.version_id == Classification.version_id)
        .join(SecurityLevel, SecurityLevel.id == Classification.level_id, isouter=True)
        .join(DocType, DocType.id == Classification.doc_type_id, isouter=True)
        .distinct()
        .where(
            Document.tenant_id == user.tenant_id,
            Document.deleted_at.is_(None),
            func.coalesce(SecurityLevel.rank, DEFAULT_FLOOR_RANK) <= user.clearance_rank,
        )
    )
    stmt = _department_axis(stmt, user)
    if level is not None:
        stmt = stmt.where(SecurityLevel.name == level.value)
    if doc_type is not None:
        stmt = stmt.where(DocType.name == doc_type)
    return stmt


def _department_axis(stmt: Select[Any], user: UserCtx) -> Select[Any]:
    """Axis 2 (#25): department-scoped docs need subtree visibility; docs with
    no owning department are tenant-wide."""
    if user.visible_department_ids:
        return stmt.where(
            or_(
                Document.department_id.is_(None),
                Document.department_id.in_(user.visible_department_ids),
            )
        )
    return stmt.where(Document.department_id.is_(None))


# The visibility predicate above is composed INTO both subqueries below —
# never applied after fusion (#27).


def compose_keyword_subquery(candidates: Subquery, q: str) -> Select[Any]:
    """Keyword arm: tsv @@ plainto_tsquery over the filtered candidates,
    ts_rank-ordered with an explicit rank window, capped at KEYWORD_ARM_LIMIT.
    The LIMIT applies AFTER the window, so it truncates a ranked filtered set,
    never a filter applied to a ranked one."""
    tsquery = func.plainto_tsquery("english", q)
    rank_expr = func.ts_rank(candidates.c.tsv, tsquery)
    return (
        select(
            candidates.c.document_id,
            candidates.c.version_id,
            func.row_number().over(order_by=rank_expr.desc()).label("kw_rank"),
        )
        .where(candidates.c.tsv.op("@@")(tsquery))
        .order_by(rank_expr.desc())
        .limit(KEYWORD_ARM_LIMIT)
    )


def compose_vector_subquery(
    candidates: Subquery, query_embedding: Sequence[float] | None = None
) -> Select[Any]:
    """Vector arm: pgvector cosine ranking over the SAME filtered candidates.

    ``query_embedding is None`` — no artifact, no encoder, or a query we could
    not embed — keeps the historic zero-row shape, so hybrid search degrades to
    keyword-only rather than failing. The visibility predicate rides inside the
    candidates subquery either way (#27); as with the keyword arm the LIMIT
    applies AFTER the window, truncating a ranked filtered set.

    Only ranks leave this arm. Cosine distance is never returned or compared
    against ``ts_rank``; fusion is reciprocal-rank only (#29).
    """
    if query_embedding is None:
        return select(
            candidates.c.document_id,
            candidates.c.version_id,
            func.row_number().over(order_by=candidates.c.version_id).label("vec_rank"),
        ).where(false())
    distance = candidates.c.embedding.cosine_distance(list(query_embedding))
    return (
        select(
            candidates.c.document_id,
            candidates.c.version_id,
            func.row_number().over(order_by=distance.asc()).label("vec_rank"),
        )
        .where(candidates.c.embedding.is_not(None))
        .order_by(distance.asc())
        .limit(VECTOR_ARM_LIMIT)
    )
