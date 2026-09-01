# backend/tests/api/test_document_sorting.py
"""Sorting must stay keyset-paginated (#32) and must not drop rows.

The dangerous case is a nullable sort column: `(NULL, id) > (value, id)` is
NULL, not false, so an uncoalesced keyset predicate silently drops every
unclassified row at a page boundary.
"""

from __future__ import annotations

from typing import Any

import pytest

SORTABLE = ["created_at", "filename", "status", "level", "doc_type"]


@pytest.mark.parametrize("field", SORTABLE)
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_sort_params_reach_the_query(
    client: Any, captured_page_args: dict[str, Any], field: str, direction: str
) -> None:
    client.get(f"/v1/documents?sort={field}&direction={direction}")
    assert captured_page_args["sort_field"] == field
    assert captured_page_args["direction"] == direction


def test_sort_defaults_to_created_at_asc(client: Any, captured_page_args: dict[str, Any]) -> None:
    client.get("/v1/documents")
    assert captured_page_args["sort_field"] == "created_at"
    assert captured_page_args["direction"] == "asc"


@pytest.mark.parametrize("bad", ["owner", "size", "'; DROP TABLE documents;--"])
def test_unknown_sort_field_is_rejected(client: Any, bad: str) -> None:
    """A silently ignored sort is how the filter bug shipped. Reject instead."""
    assert client.get(f"/v1/documents?sort={bad}").status_code == 400


def test_cursor_carries_the_sort_and_is_rejected_under_a_different_one(client: Any) -> None:
    """A page cannot be re-interpreted under a sort it was not produced by."""
    import uuid

    from app.api.v1.documents import encode_cursor

    token = encode_cursor("filename", "asc", "a.pdf", uuid.uuid4())
    response = client.get(f"/v1/documents?sort=status&direction=asc&cursor={token}")
    assert response.status_code == 400
