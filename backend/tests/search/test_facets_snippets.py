"""Pure snippet windows + facet plumbing behaviour (#28).

snippet_for is a pure function tested against boundary cases. Facet functions
are thin GROUP BY wrappers over the shared candidate set; their execution goes
through the ``_run_group_counts`` seam, faked here.
"""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import column, select

from app.search import hybrid
from app.search.hybrid import doc_type_facet_counts, facet_counts, snippet_for
from tests.search.conftest import SENTINEL_SESSION


def vid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


def dummy_candidates(column_name: str) -> Any:
    """Minimal stand-in exposing ``.c.<column_name>`` for the GROUP BY wrap."""
    return select(column(column_name)).subquery()


# --- snippet_for: window boundaries ---


def test_match_center_window_without_ellipses_when_text_short() -> None:
    text = "The vendor contract expires soon."

    assert snippet_for(vid(1), text, "contract") == text


def test_match_at_start_gets_no_leading_ellipsis() -> None:
    text = "Contract terms follow. " + "x" * 300

    out = snippet_for(vid(1), text, "contract")

    assert out.startswith("Contract")
    assert not out.startswith("…")
    assert out.endswith("…")


def test_match_at_end_gets_no_trailing_ellipsis() -> None:
    text = "x" * 300 + " signed contract"

    out = snippet_for(vid(1), text, "contract")

    assert out.startswith("…")
    assert out.endswith("contract")


def test_absent_term_falls_back_to_leading_text() -> None:
    out = snippet_for(vid(1), "y" * 500, "nothing-here")

    assert out == "y" * 240 + "…"


def test_snippet_never_exceeds_hard_cap() -> None:
    text = "a" * 1000 + " needle " + "b" * 1000

    assert len(snippet_for(vid(1), text, "needle")) <= 280


def test_matching_is_case_insensitive() -> None:
    text = "Signed CONTRACT above."

    assert "CONTRACT" in snippet_for(vid(1), text, "contract")


def test_multi_term_query_uses_earliest_occurrence() -> None:
    out = snippet_for(vid(1), "beta comes before alpha", "alpha beta")

    assert out.startswith("beta")


def test_empty_text_returns_empty_snippet() -> None:
    assert snippet_for(vid(1), "", "contract") == ""


# --- facet plumbing over the shared candidate set ---


def _patch_counts(monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str | None, int]]) -> None:
    async def fake(session: Any, stmt: Any) -> list[tuple[str | None, int]]:
        return rows

    monkeypatch.setattr(hybrid, "_run_group_counts", fake)


def test_level_facets_group_candidate_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_counts(monkeypatch, [("internal", 5), ("restricted", 2)])

    counts = asyncio.run(facet_counts(SENTINEL_SESSION, dummy_candidates("level_name")))

    assert counts == {"internal": 5, "restricted": 2}


def test_null_doc_type_facets_labelled_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_counts(monkeypatch, [(None, 3), ("msa", 1)])

    counts = asyncio.run(doc_type_facet_counts(SENTINEL_SESSION, dummy_candidates("doc_type_name")))

    assert counts == {"unknown": 3, "msa": 1}
