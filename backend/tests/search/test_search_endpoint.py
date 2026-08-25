"""GET /v1/search: authz, validation and response shaping through patched seams.

Real under test: require(VIEW) gating, q/limit/level validation, RRF-ordered
response assembly, facet echo. Data access is faked at the module-level seams
in ``app.search.hybrid``; SQL shape is proven in test_visibility_filter_sql.
"""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.search import hybrid
from app.search.hybrid import ResultMeta
from tests.search.conftest import make_user

V1 = uuid.UUID(int=1)
V2 = uuid.UUID(int=2)
D1 = uuid.UUID(int=101)
D2 = uuid.UUID(int=102)


def install_seams(
    monkeypatch: pytest.MonkeyPatch,
    *,
    keyword_rows: list[Any],
    meta: dict[uuid.UUID, ResultMeta],
    snippets: dict[uuid.UUID, str] | None = None,
    level_facets: list[tuple[str | None, int]] | None = None,
    doc_type_facets: list[tuple[str | None, int]] | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def keyword_arm(session: Any, stmt: Any) -> list[Any]:
        captured["keyword_stmt"] = stmt
        return keyword_rows

    async def vector_arm(session: Any, stmt: Any) -> list[Any]:
        return []

    async def group_counts(session: Any, stmt: Any) -> list[tuple[str | None, int]]:
        columns = set(stmt.selected_columns.keys())
        is_doc_types = "doc_type_name" in columns
        captured.setdefault("facet_stmts", []).append(str(stmt.selected_columns.keys()))
        return (doc_type_facets or []) if is_doc_types else (level_facets or [])

    async def load_meta(
        session: Any, candidates: Any, version_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, ResultMeta]:
        captured["version_ids"] = list(version_ids)
        return meta

    async def snippet_text(session: Any, version_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        return snippets or {}

    for name, fake in (
        ("_run_keyword_arm", keyword_arm),
        ("_run_vector_arm", vector_arm),
        ("_run_group_counts", group_counts),
        ("_load_result_documents", load_meta),
        ("_load_snippet_text", snippet_text),
    ):
        monkeypatch.setattr(hybrid, name, fake)
    return captured


def test_search_returns_fused_payload(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        SimpleNamespace(version_id=V1, document_id=D1),
        SimpleNamespace(version_id=V2, document_id=D2),
    ]
    meta = {
        V1: ResultMeta(filename="a.pdf", level="internal", doc_type="msa"),
        V2: ResultMeta(filename="b.pdf", level="confidential", doc_type=None),
    }
    captured = install_seams(
        monkeypatch,
        keyword_rows=rows,
        meta=meta,
        snippets={V1: "contract text here"},
        level_facets=[("internal", 2)],
        doc_type_facets=[("msa", 1), (None, 1)],
    )

    response = client.get("/v1/search", params={"q": "contract"})
    body = response.json()

    assert response.status_code == 200
    assert [r["version_id"] for r in body["results"]] == [str(V1), str(V2)]
    assert body["results"][0]["filename"] == "a.pdf"
    assert body["results"][0]["level"] == "internal"
    assert body["results"][0]["snippet"] == "contract text here"
    assert body["results"][0]["score"] == pytest.approx(1 / 61)
    assert body["results"][1]["snippet"] == ""
    assert body["results"][1]["score"] == pytest.approx(1 / 62)
    assert body["facets"] == {"levels": {"internal": 2}, "doc_types": {"msa": 1, "unknown": 1}}
    assert body["total_candidates"] == 2
    assert captured["version_ids"] == [V1, V2]


def test_level_filter_lands_inside_candidate_statement(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = install_seams(monkeypatch, keyword_rows=[], meta={})

    response = client.get("/v1/search", params={"q": "contract", "level": "restricted"})

    assert response.status_code == 200
    params = captured["keyword_stmt"].compile(dialect=postgresql.dialect()).params
    assert "restricted" in [str(value) for value in params.values()]


def test_viewer_role_can_search(client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    install_seams(monkeypatch, keyword_rows=[], meta={})
    client = client_factory(user=make_user(role="viewer"))

    assert client.get("/v1/search", params={"q": "x"}).status_code == 200


def test_unknown_role_forbidden(client_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    install_seams(monkeypatch, keyword_rows=[], meta={})
    client = client_factory(user=make_user(role="auditor"))

    response = client.get("/v1/search", params={"q": "x"})

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"


def test_anonymous_rejected_with_401(anon_client: Any) -> None:
    response = anon_client.get("/v1/search", params={"q": "x"})

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"


def test_blank_query_rejected_as_400_problem(client: Any) -> None:
    response = client.get("/v1/search", params={"q": "   "})

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"


def test_missing_query_rejected_as_400_problem(client: Any) -> None:
    response = client.get("/v1/search")

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"


@pytest.mark.parametrize("limit", [0, 99])
def test_limit_outside_bounds_rejected(client: Any, limit: int) -> None:
    assert client.get("/v1/search", params={"q": "x", "limit": limit}).status_code == 400


def test_invalid_level_value_rejected(client: Any) -> None:
    response = client.get("/v1/search", params={"q": "x", "level": "topsecret"})

    assert response.status_code == 400
