# ruff: noqa: B008 -- Depends() in argument defaults is the FastAPI idiom;
# the Annotated[] form fails to resolve under CPython 3.14 PEP 649 lazy
# annotations with fastapi 0.141 (ForwardRef evaluation bug).


"""DEV-ONLY presigned-URL verification endpoint (local storage backend, D8).

Mounted by ``create_app`` ONLY when ``settings.storage_backend == "local"``.
The filesystem backend has no server-side enforcement of its HMAC presigns,
so this router is the dev counterpart of MinIO's native signed GET. It must
never be reachable in a production deployment: production uses the MinIO
backend and this router is not even registered there.

Signatures come from ``LocalStorage.presign`` (``?expires=&sig=``); verification
is constant-time and expiry-checked. Bodies stream as
``application/octet-stream`` — dev tooling does not need accurate media types.
"""

import time
from typing import BinaryIO

from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse
from starlette.status import HTTP_403_FORBIDDEN

from app.api import deps
from app.api.v1.documents import _stream_handle
from app.storage.base import Storage

router = APIRouter(tags=["dev-storage"])


def _now() -> float:
    """Clock seam so tests can travel into the future."""
    return time.time()


def _content_length(handle: BinaryIO) -> int:
    end = handle.seek(0, 2)
    handle.seek(0)
    return int(end)


@router.get("/dev-storage/{key:path}")
async def get_dev_object(
    key: str,
    expires: int,
    sig: str,
    storage: Storage = Depends(deps.get_storage),
) -> StreamingResponse:
    verify = getattr(storage, "verify_presign", None)
    if not callable(verify) or not verify(key, expires, sig, now=_now()):
        raise HTTPException(HTTP_403_FORBIDDEN, "invalid or expired signature")
    handle = storage.open(key)
    return StreamingResponse(
        _stream_handle(handle),
        media_type="application/octet-stream",
        headers={"Content-Length": str(_content_length(handle))},
    )
