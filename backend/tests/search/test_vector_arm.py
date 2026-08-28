"""The pgvector arm: live ranking, still filtered INSIDE the arm (#27/#28/#29).

No database. Statements compile against the postgresql dialect and their SQL
text / bound params are inspected, exactly like test_visibility_filter_sql.py.

What must hold once the arm ranks for real:

* the candidate set projects ``embedding``, so the arm never has to reach past
  the visibility predicate to a raw ``document_text`` row to rank;
* the visibility predicates appear exactly ONCE, inside the candidates
  subquery the arm selects FROM — never re-applied, never applied after;
* only a RANK leaves the arm. Cosine distance is not projected and never meets
  ``ts_rank``; fusion is reciprocal-rank only, k=60 (#29);
* with no query embedding (no artifact / no encoder) the arm is zero-row and
  search degrades to keyword-only rather than failing.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.search import hybrid
from app.search.filters import (
    VECTOR_ARM_LIMIT,
    build_visible_candidates,
    compose_vector_subquery,
)
from tests.search.conftest import SENTINEL_SESSION, make_user

TENANT = uuid.UUID(int=0xA000)
QUERY_VECTOR = [0.1] * 384


def compile_sql(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def compile_params(stmt: Any) -> dict[str, Any]:
    return stmt.compile(dialect=postgresql.dialect()).params


def param_values(stmt: Any) -> list[str]:
    flat: list[str] = []
    for value in compile_params(stmt).values():
        if isinstance(value, (list, tuple)):
            flat.extend(str(item) for item in value)
        else:
            flat.append(str(value))
    return flat


def candidates() -> Any:
    return build_visible_candidates(make_user(tenant_id=TENANT)).subquery(name="candidates")


# --- candidate set carries the ranking signal -------------------------------


def test_candidates_project_the_embedding_column() -> None:
    stmt = build_visible_candidates(make_user(tenant_id=TENANT))

    assert "embedding" in stmt.selected_columns
    assert "document_text.embedding" in compile_sql(stmt)


# --- active arm --------------------------------------------------------------


def test_vector_arm_ranks_by_cosine_distance_over_the_filtered_candidates() -> None:
    vec = compose_vector_subquery(candidates(), QUERY_VECTOR)
    sql = compile_sql(vec)

    assert "<=>" in sql  # pgvector cosine distance
    assert "row_number() OVER (ORDER BY" in sql
    assert "ASC)" in sql
    assert "IS NOT NULL" in sql  # unembedded rows cannot rank
    assert "LIMIT" in sql
    assert VECTOR_ARM_LIMIT in compile_params(vec).values()
    assert "AS candidates" in sql


def test_vector_arm_composes_visibility_inside_itself_exactly_once() -> None:
    vec = compose_vector_subquery(candidates(), QUERY_VECTOR)
    sql = compile_sql(vec)

    assert "AS candidates" in sql
    assert sql.count("deleted_at") == 1
    assert sql.count("documents.tenant_id") == 1
    assert str(TENANT) in param_values(vec)
    # The distance predicate sits OUTSIDE the candidates subquery text, i.e.
    # ranking happens on top of the filtered set, never before it.
    assert sql.index("AS candidates") < sql.index("<=>", sql.index("AS candidates"))


def test_vector_arm_projects_ranks_only_never_a_score() -> None:
    """#29: raw cosine distance must not be comparable against ts_rank."""
    vec = compose_vector_subquery(candidates(), QUERY_VECTOR)

    assert set(vec.selected_columns.keys()) == {"document_id", "version_id", "vec_rank"}


def test_facet_filters_still_reach_the_vector_arm() -> None:
    """A doc_type/level facet filter lives in the candidates both arms share."""
    from app.domain.models import LevelName

    filtered = build_visible_candidates(
        make_user(tenant_id=TENANT), level=LevelName.RESTRICTED, doc_type="Invoice"
    ).subquery(name="candidates")
    sql = compile_sql(compose_vector_subquery(filtered, QUERY_VECTOR))

    assert "security_levels.name" in sql
    assert "doc_types.name" in sql


# --- graceful degradation ----------------------------------------------------


def test_no_query_embedding_yields_a_zero_row_arm() -> None:
    """No artifact / no encoder: hybrid search degrades to keyword-only."""
    vec = compose_vector_subquery(candidates(), None)
    sql = compile_sql(vec)

    assert "WHERE false" in sql
    assert "<=>" not in sql
    assert "row_number() OVER (ORDER BY" in sql
    assert set(vec.selected_columns.keys()) == {"document_id", "version_id", "vec_rank"}


def test_omitting_the_embedding_argument_is_the_degraded_path() -> None:
    assert "WHERE false" in compile_sql(compose_vector_subquery(candidates()))


# --- orchestration: the arm is driven by the caller's vector -----------------


def _install_arms(
    monkeypatch: pytest.MonkeyPatch,
    *,
    keyword: list[Any],
    vector: list[Any],
    captured: dict[str, Any],
) -> None:
    async def keyword_arm(session: Any, stmt: Any) -> list[Any]:
        return keyword

    async def vector_arm(session: Any, stmt: Any) -> list[Any]:
        captured["vector_sql"] = compile_sql(stmt)
        return vector

    async def group_counts(session: Any, stmt: Any) -> list[tuple[str | None, int]]:
        return [("internal", 2)] if "level_name" in stmt.selected_columns else []

    async def load_meta(session: Any, cands: Any, version_ids: list[uuid.UUID]) -> dict[Any, Any]:
        return {
            vid: hybrid.ResultMeta(filename=f"{vid}.pdf", level="internal", doc_type="Invoice")
            for vid in version_ids
        }

    async def snippet_text(session: Any, version_ids: list[uuid.UUID]) -> dict[Any, str]:
        return {}

    for name, fake in (
        ("_run_keyword_arm", keyword_arm),
        ("_run_vector_arm", vector_arm),
        ("_run_group_counts", group_counts),
        ("_load_result_documents", load_meta),
        ("_load_snippet_text", snippet_text),
    ):
        monkeypatch.setattr(hybrid, name, fake)


def _row(n: int) -> Any:
    return type("Row", (), {"version_id": uuid.UUID(int=n), "document_id": uuid.UUID(int=n + 100)})


def test_search_documents_activates_the_arm_with_the_supplied_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _install_arms(monkeypatch, keyword=[_row(1)], vector=[_row(2)], captured=captured)

    result = asyncio.run(
        hybrid.search_documents(
            SENTINEL_SESSION,
            make_user(tenant_id=TENANT),
            "vendor contract",
            query_embedding=QUERY_VECTOR,
        )
    )

    assert "<=>" in captured["vector_sql"]
    # Both arms contributed rank 1, so both score 1/(60+1) and tie-break on id.
    assert {item.version_id for item in result.items} == {uuid.UUID(int=1), uuid.UUID(int=2)}
    assert all(item.score == pytest.approx(1 / (hybrid.RRF_K + 1)) for item in result.items)


def test_search_documents_stays_keyword_only_without_a_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _install_arms(monkeypatch, keyword=[_row(1)], vector=[], captured=captured)

    result = asyncio.run(
        hybrid.search_documents(SENTINEL_SESSION, make_user(tenant_id=TENANT), "vendor contract")
    )

    assert "WHERE false" in captured["vector_sql"]
    assert [item.version_id for item in result.items] == [uuid.UUID(int=1)]


def test_a_document_ranked_by_both_arms_outranks_one_ranked_by_either(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RRF with k=60 unchanged: arm hits ADD, and only ranks are summed (#29)."""
    captured: dict[str, Any] = {}
    both, kw_only, vec_only = _row(1), _row(2), _row(3)
    _install_arms(monkeypatch, keyword=[kw_only, both], vector=[vec_only, both], captured=captured)

    result = asyncio.run(
        hybrid.search_documents(
            SENTINEL_SESSION,
            make_user(tenant_id=TENANT),
            "vendor contract",
            query_embedding=QUERY_VECTOR,
        )
    )

    assert result.items[0].version_id == uuid.UUID(int=1)
    assert result.items[0].score == pytest.approx(2 / (hybrid.RRF_K + 2))


# --- endpoint: the query embedding is computed and threaded through ---------


def test_endpoint_threads_the_query_embedding_into_the_vector_arm(
    monkeypatch: pytest.MonkeyPatch, client_factory: Any
) -> None:
    from app.api.v1 import search as search_route

    captured: dict[str, Any] = {}
    _install_arms(monkeypatch, keyword=[], vector=[_row(4)], captured=captured)
    monkeypatch.setattr(search_route, "_encode_query", lambda _settings, q: QUERY_VECTOR)

    response = client_factory(user=make_user(tenant_id=TENANT)).get(
        "/v1/search", params={"q": "vendor contract"}
    )

    assert response.status_code == 200
    assert "<=>" in captured["vector_sql"]
    assert [hit["version_id"] for hit in response.json()["results"]] == [str(uuid.UUID(int=4))]


def test_endpoint_still_answers_when_no_model_can_embed_the_query(
    monkeypatch: pytest.MonkeyPatch, client_factory: Any
) -> None:
    """The REAL _encode_query runs: this host has no encoder, so it yields None."""
    captured: dict[str, Any] = {}
    _install_arms(monkeypatch, keyword=[_row(5)], vector=[], captured=captured)

    response = client_factory(user=make_user(tenant_id=TENANT)).get(
        "/v1/search", params={"q": "vendor contract"}
    )

    assert response.status_code == 200
    assert "WHERE false" in captured["vector_sql"]
    assert [hit["version_id"] for hit in response.json()["results"]] == [str(uuid.UUID(int=5))]
