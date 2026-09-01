# backend/tests/api/test_sort_cursor.py
"""The cursor must carry its own sort, so a page cannot change sort mid-walk."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.api.v1.documents import decode_cursor, encode_cursor


def test_roundtrip_preserves_field_direction_value_and_id() -> None:
    doc_id = uuid.uuid4()
    when = datetime(2026, 9, 1, 12, 30, tzinfo=UTC)
    token = encode_cursor("created_at", "desc", when, doc_id)
    cur = decode_cursor(token)
    assert cur.field == "created_at"
    assert cur.direction == "desc"
    assert cur.value == when
    assert cur.document_id == doc_id


def test_roundtrip_supports_a_text_sort_value() -> None:
    doc_id = uuid.uuid4()
    token = encode_cursor("filename", "asc", "invoice.pdf", doc_id)
    cur = decode_cursor(token)
    assert cur.field == "filename"
    assert cur.value == "invoice.pdf"


def test_roundtrip_supports_a_null_sort_value() -> None:
    """Unclassified rows sort by a NULL doc_type; the cursor must survive it."""
    doc_id = uuid.uuid4()
    cur = decode_cursor(encode_cursor("doc_type", "asc", None, doc_id))
    assert cur.value is None
    assert cur.document_id == doc_id


@pytest.mark.parametrize(
    "bad",
    ["", "not-base64!!", "YWJj", "eyJmaWVsZCI6ICJvd25lciJ9"],
    ids=["empty", "not_b64", "b64_but_not_our_shape", "unknown_sort_field"],
)
def test_unusable_cursor_is_a_400_that_leaks_nothing(bad: str) -> None:
    with pytest.raises(HTTPException) as exc:
        decode_cursor(bad)
    assert exc.value.status_code == 400
    assert exc.value.detail == "invalid cursor"
