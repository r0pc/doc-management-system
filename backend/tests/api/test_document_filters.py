"""status / security_level must filter, and must do so inside the query.

Filtering after the page is cut yields short pages and leaks how many rows the
caller could not see.
"""

from __future__ import annotations

import pytest
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY


def test_status_filter_reaches_the_query(client, captured_page_args) -> None:  # noqa: ANN001
    client.get("/v1/documents?status=failed")
    assert captured_page_args["status"] == "failed"


def test_level_filter_reaches_the_query(client, captured_page_args) -> None:  # noqa: ANN001
    client.get("/v1/documents?security_level=confidential")
    assert captured_page_args["level"] == "confidential"


def test_absent_filters_are_none(client, captured_page_args) -> None:  # noqa: ANN001
    client.get("/v1/documents")
    assert captured_page_args.get("status") is None
    assert captured_page_args.get("level") is None


@pytest.mark.parametrize("bad", ["deleted", "'; DROP TABLE documents;--", "READY"])
def test_unknown_status_is_rejected_not_ignored(client, bad: str) -> None:  # noqa: ANN001
    """A silently ignored filter is how this bug shipped. Reject instead."""
    assert client.get(f"/v1/documents?status={bad}").status_code == 400
