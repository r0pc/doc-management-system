"""FastAPI application factory. API routers arrive in later waves."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    admin,
    audit,
    dev_auth,
    dev_storage,
    documents,
    events,
    review,
    search,
    uploads,
)
from app.api.v1.errors import register_error_handlers
from app.config import Settings, validate_runtime


def _under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup validation is skipped under pytest so unit tests stay hermetic."""
    if not _under_pytest():
        validate_runtime(Settings())
    yield


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(title="Secure Document Management System", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(uploads.router, prefix="/v1")
    app.include_router(documents.router, prefix="/v1")
    app.include_router(search.router, prefix="/v1")
    app.include_router(review.router, prefix="/v1")
    app.include_router(audit.router, prefix="/v1")
    app.include_router(admin.router, prefix="/v1")
    app.include_router(events.router, prefix="/v1")
    # D8: the HMAC-verified local-storage router exists only in dev backends.
    if settings.storage_backend == "local":
        app.include_router(dev_storage.router, prefix="/v1")
    if settings.env == "dev":
        app.include_router(dev_auth.router, prefix="/v1")
    return app


app = create_app()
