"""Pin the routes the frontend calls.

A stale image silently drops new routes; the browser sees an opaque 404 that
looks identical to a permission denial. This test makes that a red test.
"""

from __future__ import annotations

import pytest

from app.main import app

REQUIRED_ROUTES = [
    ("GET", "/v1/documents"),
    ("GET", "/v1/documents/{document_id}"),
    ("GET", "/v1/documents/{document_id}/content"),
    ("GET", "/v1/documents/{document_id}/view"),
    ("GET", "/v1/documents/{document_id}/preview"),
    ("GET", "/v1/documents/{document_id}/findings"),
    ("GET", "/v1/documents/{document_id}/jobs"),
    ("POST", "/v1/documents/{document_id}/classification"),
    ("POST", "/v1/uploads"),
    ("POST", "/v1/uploads/{upload_id}/complete"),
]


_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"})


def _registered() -> set[tuple[str, str]]:
    """The route table as the frontend (and `/openapi.json`) sees it.

    FastAPI >=0.141 defers ``include_router`` into a lazy ``_IncludedRouter``
    wrapper: ``app.routes`` no longer flattens included routers' routes, so
    ``route.path``/``route.methods`` are ``None`` for every one of them.
    ``app.openapi()`` forces the same resolution the live server exposes at
    ``/openapi.json`` (what Step 3 curls), so it stays the authoritative,
    version-proof source for "is this route actually reachable".
    """
    schema = app.openapi()
    found: set[tuple[str, str]] = set()
    for path, operations in schema["paths"].items():
        for method in operations:
            if method.upper() in _HTTP_METHODS:
                found.add((method.upper(), path))
    return found


@pytest.mark.parametrize(("method", "path"), REQUIRED_ROUTES)
def test_route_is_registered(method: str, path: str) -> None:
    assert (method, path) in _registered(), (
        f"{method} {path} is not registered. The frontend calls it; if this "
        "fails the deployed image is stale or the route was renamed."
    )
