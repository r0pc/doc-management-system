"""RFC 7807 problem+json error envelope for the whole API surface.

Canonical 404 (#31): :func:`not_found` returns THE byte-stable body every
document-not-found path uses — missing uuid, foreign-tenant row (invisible
under RLS), clearance/department denial and deleted rows all funnel through
this single function, so bodies are identical across tenants and causes.

Authorize-BEFORE-fetch pattern: handlers fetch through RLS-bound sessions
(foreign rows vanish at the SQL layer), then re-check ``policy.can_access``
server-side (#33). Both outcomes — and the not-found outcome — collapse into
the same ``not_found()`` response with no branching on existence, giving
timing parity: one fetch, one gate, one response shape regardless of whether
the document exists. Error bodies never carry filenames or matched text.

The fallback 500 handler is deliberately sanitised: it never echoes exception
text, which may contain storage keys or SQL fragments.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

import jwt
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_CONTENT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from app.extraction.base import UnknownMimeError
from app.extraction.registry import UnsupportedMimeError
from app.storage.base import BlobExistsError, ImmutableKeyError

PROBLEM_MEDIA_TYPE = "application/problem+json"


def problem_response(
    status: int,
    title: str,
    *,
    detail: str | None = None,
    instance: str | None = None,
    headers: dict[str, str] | None = None,
    extra: dict[str, object] | None = None,
) -> JSONResponse:
    """Build one RFC 7807 response; None fields are omitted for byte stability."""
    body: dict[str, object] = {"type": "about:blank", "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    if instance is not None:
        body["instance"] = instance
    if extra:
        body.update(extra)
    return JSONResponse(
        status_code=status, content=body, media_type=PROBLEM_MEDIA_TYPE, headers=headers
    )


def not_found() -> JSONResponse:
    """THE canonical 404 (#31): static body, static instance, byte-stable."""
    return problem_response(HTTP_404_NOT_FOUND, "Not Found", instance="/")


def _title_for(status: int) -> str:
    from http import HTTPStatus

    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    http_exc = cast(StarletteHTTPException, exc)
    headers: dict[str, str] = dict(http_exc.headers or {})
    return problem_response(
        http_exc.status_code,
        _title_for(http_exc.status_code),
        detail=str(http_exc.detail) if http_exc.detail is not None else None,
        instance=request.url.path,
        headers=headers or None,
    )


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Projection drops "input" values: a rejected payload may carry filenames
    # or identifiers that must never be echoed back (#31).
    validation_exc = cast(RequestValidationError, exc)
    errors = [
        {"loc": [str(part) for part in error.get("loc", ())], "msg": error.get("msg", "")}
        for error in validation_exc.errors()
    ]
    return problem_response(
        HTTP_400_BAD_REQUEST,
        "Bad Request",
        detail="request validation failed",
        instance=request.url.path,
        extra={"errors": errors},
    )


async def _unknown_mime_handler(request: Request, exc: Exception) -> JSONResponse:
    return problem_response(
        HTTP_422_UNPROCESSABLE_CONTENT,
        "Unprocessable Entity",
        detail="content matches no known file signature",
        instance=request.url.path,
    )


async def _unsupported_mime_handler(request: Request, exc: Exception) -> JSONResponse:
    return problem_response(
        HTTP_422_UNPROCESSABLE_CONTENT,
        "Unprocessable Entity",
        detail="content type identified but unsupported this phase",
        instance=request.url.path,
    )


async def _blob_exists_handler(request: Request, exc: Exception) -> JSONResponse:
    return problem_response(
        HTTP_409_CONFLICT,
        "Conflict",
        detail="conflicting blob state",
        instance=request.url.path,
    )


async def _immutable_key_handler(request: Request, exc: Exception) -> JSONResponse:
    return problem_response(
        HTTP_409_CONFLICT,
        "Conflict",
        detail="object is immutable",
        instance=request.url.path,
    )


async def _file_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    return not_found()


async def _invalid_token_handler(request: Request, exc: Exception) -> JSONResponse:
    return problem_response(
        HTTP_401_UNAUTHORIZED,
        "Unauthorized",
        detail="invalid token",
        instance=request.url.path,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _fallback_handler(request: Request, exc: Exception) -> JSONResponse:
    # Sanitised by design: exception text may embed keys, SQL or paths.
    return problem_response(
        HTTP_500_INTERNAL_SERVER_ERROR,
        "Internal Server Error",
        detail="internal error",
        instance="/",
    )


_Handler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def _register(app: FastAPI, exc_type: type[Exception], handler: object) -> None:
    """Register one handler under Starlette's broadened signature.

    Handlers are annotated with their specific exception type (they only ever
    receive what they were registered for); Starlette's stub demands the
    widened callable shape, so the cast lives here - once.
    """
    app.add_exception_handler(exc_type, cast(_Handler, handler))


def register_error_handlers(app: FastAPI) -> None:
    """Attach the envelope to the app; call once from create_app."""
    _register(app, StarletteHTTPException, _http_exception_handler)
    _register(app, RequestValidationError, _validation_error_handler)
    _register(app, UnknownMimeError, _unknown_mime_handler)
    _register(app, UnsupportedMimeError, _unsupported_mime_handler)
    _register(app, BlobExistsError, _blob_exists_handler)
    _register(app, ImmutableKeyError, _immutable_key_handler)
    _register(app, FileNotFoundError, _file_not_found_handler)
    app.add_exception_handler(jwt.InvalidTokenError, _invalid_token_handler)
    _register(app, Exception, _fallback_handler)
