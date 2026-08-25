# ruff: noqa: B008 -- Depends() in argument defaults is the FastAPI idiom;
# the Annotated[] form fails to resolve under CPython 3.14 PEP 649 lazy
# annotations with fastapi 0.141 (ForwardRef evaluation bug).


"""Server-sent events stub: GET /v1/events answers 501 until the frontend wave.

The route keeps the standard auth dependency so unauthenticated probes behave
exactly as they would against a real endpoint; the pinned problem+json body is
the contract the frontend codes against. Polling alternative:
``GET /v1/documents/{id}/jobs``.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api import deps
from app.domain.models import Action, UserCtx

router = APIRouter(prefix="/events", tags=["events"])

_NOT_IMPLEMENTED_BODY = {
    "type": "https://dms.example/problems/not-implemented",
    "title": "Not Implemented",
    "status": 501,
    "detail": "SSE arrives with frontend wave; poll GET /v1/documents/{id}/jobs meanwhile",
}


@router.get("")
async def list_events(
    user: UserCtx = Depends(deps.require(Action.VIEW)),
) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content=_NOT_IMPLEMENTED_BODY,
        media_type="application/problem+json",
    )
