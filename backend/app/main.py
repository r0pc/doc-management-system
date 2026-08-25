"""FastAPI application factory. API routers arrive in later waves."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

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
    app = FastAPI(title="Secure Document Management System", lifespan=_lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # TODO(Wave 1+): app.include_router(api_v1_router, prefix="/v1")
    return app


app = create_app()
