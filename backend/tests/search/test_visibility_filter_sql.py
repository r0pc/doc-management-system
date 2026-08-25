"""Compiled-SQL proofs that visibility filtering runs INSIDE both arms (#27).

No database: statements are compiled against the postgresql dialect and their
SQL text / bound params inspected. The companion behavioural test drives
``search_documents`` through PARAM-DRIVEN fake arms: the fakes extract the
visibility axes (tenant, clearance, departments) from the compiled statement's
bound params and filter a canned corpus with them. If the composers ever stop
embedding the predicates into the executed statement, the fakes cannot filter,
the counts diverge, and the test fails — the AGENTS-mandated proof that result
counts never vary with what the caller cannot see.
"""

import asyncio
import uuid
from collections import Counter
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.models import LevelName
from app.search import hybrid
from app.search.filters import (
    build_visible_candidates,
    compose_keyword_subquery,
    compose_vector_subquery,
)
from tests.search.conftest import SENTINEL_SESSION, make_user

TENANT = uuid.UUID(int=0xA000)
DEPT_1 = uuid.UUID(int=0xD001)
DEPT_2 = uuid.UUID(int=0xD002)


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


def facet_dimension(stmt: Any) -> str:
    """Discriminate by projected columns; SQL text is ambiguous because the
    auto-FROM inlines the candidates subquery mentioning both tables."""
    columns = set(stmt.selected_columns.keys())
    return "doc_types" if "doc_type_name" in columns else "levels"


# --- candidates: both axes embedded ---


def test_candidates_embed_tenant_deletion_and_clearance_axes() -> None:
    stmt = build_visible_candidates(make_user(tenant_id=TENANT, clearance_rank=3))
    sql = compile_sql(stmt)

    assert str(TENANT) in param_values(stmt)
    assert "deleted_at" in sql and "IS NULL" in sql
    assert "coalesce" in sql.lower()
    assert "security_levels.rank" in sql
    assert 3 in compile_params(stmt).values()


def test_candidates_department_axis_is_null_or_whitelist() -> None:
    wide = build_visible_candidates(
        make_user(tenant_id=TENANT, visible_department_ids=(DEPT_1, DEPT_2))
    )
    narrow = build_visible_candidates(make_user(tenant_id=TENANT))

    assert "department_id IS NULL" in compile_sql(wide)
    dept_params = {uuid.UUID(v) for v in param_values(wide) if v.endswith(("d001", "d002"))}
    assert {DEPT_1, DEPT_2}.issubset(dept_params)
    # No department visibility means only tenant-wide documents.
    assert compile_sql(narrow).count("department_id IS NULL") == 1


def test_optional_level_and_doc_type_filters_apply_inside_candidates() -> None:
    stmt = build_visible_candidates(
        make_user(tenant_id=TENANT), level=LevelName.RESTRICTED, doc_type="msa"
    )
    sql = compile_sql(stmt)

    assert "security_levels.name" in sql
    assert "doc_types.name" in sql
    values = param_values(stmt)
    assert "restricted" in values
    assert "msa" in values


# --- arms: predicates ride inside, ranking on top ---


def test_keyword_arm_matches_and_ranks_over_filtered_subquery() -> None:
    candidates = build_visible_candidates(make_user(tenant_id=TENANT)).subquery(name="candidates")
    kw = compose_keyword_subquery(candidates, "vendor contract")
    sql = compile_sql(kw)

    assert "@@" in sql
    assert "plainto_tsquery" in sql
    assert "ts_rank" in sql
    assert "row_number() OVER (ORDER BY" in sql
    assert "DESC)" in sql
    assert "LIMIT" in sql
    assert 100 in compile_params(kw).values()
    assert "AS candidates" in sql
    # Visibility predicates appear exactly once each — inside the candidates
    # subquery the arm selects FROM; no post-hoc copies at arm level.
    assert sql.count("deleted_at") == 1
    assert sql.count("@@") == 1
    assert str(TENANT) in param_values(kw)


def test_vector_arm_is_zero_row_scaffold_with_rank_window() -> None:
    candidates = build_visible_candidates(make_user(tenant_id=TENANT)).subquery(name="candidates")
    vec = compose_vector_subquery(candidates)
    sql = compile_sql(vec)

    assert "WHERE false" in sql
    assert "row_number() OVER (ORDER BY" in sql
    assert "@@" not in sql
    assert "AS candidates" in sql
    assert sql.count("deleted_at") == 1
    assert str(TENANT) in param_values(vec)


# --- behavioural leak-proofing: param-driven fake arms over a canned corpus ---


def _doc(
    n: int,
    *,
    level_name: str,
    level_rank: int,
    department_id: uuid.UUID | None,
    matches: bool = True,
    deleted: bool = False,
    tenant_id: uuid.UUID = TENANT,
) -> Any:
    """One canned corpus row carrying exactly the axes the SQL filters on."""
    return SimpleNamespace(
        version_id=uuid.UUID(int=n),
        document_id=uuid.UUID(int=n + 1000),
        filename=f"doc-{n}.pdf",
        level_name=level_name,
        level_rank=level_rank,
        department_id=department_id,
        doc_type_name=None,
        matches=matches,
        deleted_at=object() if deleted else None,
        tenant_id=tenant_id,
    )


def _corpus(*, all_matching: bool) -> list[Any]:
    """5 visible Internal + 7 Restricted hidden from clearance-2 callers."""
    docs = [_doc(i, level_name="internal", level_rank=2, department_id=None) for i in range(5)]
    docs += [
        _doc(i, level_name="restricted", level_rank=4, department_id=DEPT_1) for i in range(5, 12)
    ]
    if not all_matching:
        docs += [
            _doc(i, level_name="internal", level_rank=2, department_id=None, matches=False)
            for i in range(12, 15)
        ]
    return docs


def _axes_from(stmt: Any) -> tuple[uuid.UUID, int, tuple[uuid.UUID, ...]]:
    """Extract (tenant, clearance, depts) from compiled bound params.

    Value classification: the only ints are the COALESCE floor (2) and the
    caller's clearance; the lone bare UUID is the tenant; the sequence value
    is the department whitelist. Fixture-controlled shapes.
    """
    params = compile_params(stmt)
    ints = [v for v in params.values() if isinstance(v, int)]
    tenant = next(v for v in params.values() if isinstance(v, uuid.UUID))
    depts = next((tuple(v) for v in params.values() if isinstance(v, (list, tuple))), ())
    return tenant, max(ints), depts


def _visible(doc: Any, axes: tuple[uuid.UUID, int, tuple[uuid.UUID, ...]]) -> bool:
    tenant, clearance, depts = axes
    return (
        doc.tenant_id == tenant
        and doc.deleted_at is None
        and doc.level_rank <= clearance
        and (doc.department_id is None or doc.department_id in depts)
    )


def _install_param_driven_fakes(monkeypatch: pytest.MonkeyPatch, corpus: list[Any]) -> None:
    async def keyword_arm(session: Any, stmt: Any) -> list[Any]:
        axes = _axes_from(stmt)
        rows = [doc for doc in corpus if _visible(doc, axes) and doc.matches]
        rows.sort(key=lambda doc: -doc.document_id.int)  # stable canned relevance
        ranked = [
            {"version_id": doc.version_id, "document_id": doc.document_id, "kw_rank": rank}
            for rank, doc in enumerate(rows, start=1)
        ]
        return [type("Row", (), row) for row in ranked]

    async def vector_arm(session: Any, stmt: Any) -> list[Any]:
        return []

    async def group_counts(session: Any, stmt: Any) -> list[tuple[str | None, int]]:
        axes = _axes_from(stmt)
        counts: Counter[str | None] = Counter()
        for doc in corpus:
            if not _visible(doc, axes):
                continue
            if facet_dimension(stmt) == "doc_types":
                counts[doc.doc_type_name] += 1
            else:
                counts[doc.level_name] += 1
        return list(counts.items())

    async def load_meta(session: Any, candidates: Any, version_ids: list[uuid.UUID]) -> dict:
        by_id = {doc.version_id: doc for doc in corpus}
        return {
            vid: hybrid.ResultMeta(
                filename=by_id[vid].filename,
                level=by_id[vid].level_name,
                doc_type=None,
            )
            for vid in version_ids
        }

    async def snippet_text(session: Any, version_ids: list[uuid.UUID]) -> dict:
        return {}

    monkeypatch.setattr(hybrid, "_run_keyword_arm", keyword_arm)
    monkeypatch.setattr(hybrid, "_run_vector_arm", vector_arm)
    monkeypatch.setattr(hybrid, "_run_group_counts", group_counts)
    monkeypatch.setattr(hybrid, "_load_result_documents", load_meta)
    monkeypatch.setattr(hybrid, "_load_snippet_text", snippet_text)


def _search(user: Any, q: str = "contract") -> Any:
    return asyncio.run(hybrid.search_documents(SENTINEL_SESSION, user, q))


def test_page_length_and_facets_never_reflect_invisible_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_param_driven_fakes(monkeypatch, _corpus(all_matching=True))

    low = _search(make_user(tenant_id=TENANT, clearance_rank=2))
    wide = _search(make_user(tenant_id=TENANT, clearance_rank=4, visible_department_ids=(DEPT_1,)))

    # Caller A: page length and facet totals derive exclusively from A's set.
    assert len(low.items) == 5
    assert low.total_candidates == 5
    assert sum(low.level_facets.values()) == 5
    assert set(low.level_facets) == {"internal"}
    payload = repr((low.items, low.level_facets, low.doc_type_facets))
    assert "restricted" not in payload

    # Superuser B sees all 12; A's ordering is B's minus the invisible rows.
    assert len(wide.items) == 12
    assert wide.total_candidates == 12
    assert wide.level_facets == {"internal": 5, "restricted": 7}
    low_ids = [item.version_id for item in low.items]
    wide_ids = [item.version_id for item in wide.items]
    assert low_ids == [vid for vid in wide_ids if vid in set(low_ids)]


def test_facets_describe_visible_corpus_not_query_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_param_driven_fakes(monkeypatch, _corpus(all_matching=False))

    result = _search(make_user(tenant_id=TENANT, clearance_rank=2))

    # 5 matching results, but facets/total cover the whole visible candidate
    # corpus (8 = 5 matching + 3 non-matching) — a count is information (#28).
    assert len(result.items) == 5
    assert result.total_candidates == 8
    assert result.level_facets == {"internal": 8}


def test_orchestrator_adds_no_filtering_of_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Arms are the sole visibility authority: whatever they return survives
    fusion untouched — proving no post-fusion filter exists downstream (#27)."""
    row = type("Row", (), {"version_id": uuid.UUID(int=7), "document_id": uuid.UUID(int=9)})
    meta = {
        uuid.UUID(int=7): hybrid.ResultMeta(filename="x.pdf", level="restricted", doc_type=None)
    }

    async def keyword_arm(session: Any, stmt: Any) -> list[Any]:
        return [row]

    async def vector_arm(session: Any, stmt: Any) -> list[Any]:
        return []

    async def group_counts(session: Any, stmt: Any) -> list[tuple[str | None, int]]:
        return [("restricted", 1)] if facet_dimension(stmt) == "levels" else []

    async def load_meta(session: Any, candidates: Any, version_ids: list[uuid.UUID]) -> dict:
        return meta

    async def snippet_text(session: Any, version_ids: list[uuid.UUID]) -> dict:
        return {}

    for name, fake in (
        ("_run_keyword_arm", keyword_arm),
        ("_run_vector_arm", vector_arm),
        ("_run_group_counts", group_counts),
        ("_load_result_documents", load_meta),
        ("_load_snippet_text", snippet_text),
    ):
        monkeypatch.setattr(hybrid, name, fake)

    result = _search(make_user(tenant_id=TENANT, clearance_rank=1))

    assert [item.version_id for item in result.items] == [uuid.UUID(int=7)]
