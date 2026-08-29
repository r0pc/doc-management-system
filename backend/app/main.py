"""FastAPI application factory. API routers arrive in later waves."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
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


def _assert_psycopg_compatible_loop() -> None:
    """Refuse to serve on an event loop psycopg's async mode cannot use.

    On Windows, ``asyncio``'s default is ``ProactorEventLoop`` and psycopg
    raises ``InterfaceError`` on every connection attempt. The server itself
    starts fine, so the symptom is a 500 on every database-backed request with
    the real cause buried in a traceback — a startup refusal with an
    actionable message is strictly better.

    Setting the event-loop POLICY does not help: uvicorn >= 0.36 passes an
    explicit ``loop_factory`` and picks ProactorEventLoop on Windows unless
    ``use_subprocess`` is set (``--reload`` or ``--workers > 1``), which is why
    the documented ``--reload`` workflow works and a bare invocation does not.
    Nothing importable can override that from here, so this checks and reports
    rather than pretending to fix it.
    """
    if sys.platform != "win32":
        return
    loop_name = type(asyncio.get_running_loop()).__name__
    if "Proactor" not in loop_name:
        return
    msg = (
        f"psycopg's async mode cannot run on {loop_name}, so every database "
        "request would fail. On Windows, start the API with --reload (which "
        "makes uvicorn select an event loop psycopg supports), or run the "
        "stack under docker compose."
    )
    raise RuntimeError(msg)


def _configure_app_logging() -> None:
    """Give application loggers somewhere to go.

    uvicorn installs handlers on its own ``uvicorn.*`` loggers and leaves the
    root logger bare, so every ``logging.getLogger(__name__)`` call in this
    package resolved to a logger with no handler. Anything below WARNING was
    dropped outright and warnings fell through to ``logging.lastResort`` with
    no timestamp or logger name — which is how a 503 with a deliberate
    ``logger.exception`` next to it can still produce an empty log.

    Only applied when nothing else has configured the root logger, so a real
    deployment's logging config (or pytest's caplog) still wins.
    """
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def _under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup validation is skipped under pytest so unit tests stay hermetic."""
    if not _under_pytest():
        validate_runtime(Settings())
        _assert_psycopg_compatible_loop()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Router mounting is a startup-time decision, not a DI one.

    Which routers exist depends on ``settings`` — the dev-only surfaces below
    must be absent from the process, not merely overridden per request — so
    callers that run under non-default configuration (tests, embedded hosts)
    have to pass the SAME Settings they inject via ``deps.get_settings``.
    Defaults to reading the environment, which is what uvicorn does.
    """
    settings = settings if settings is not None else Settings()
    _configure_app_logging()
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
    # Both conditions matter: STORAGE_BACKEND defaults to "local", so gating on
    # the backend alone would mount an object read/write surface — signed with
    # the dev HMAC secret, which is empty in prod — into a production process.
    # validate_runtime refuses that combination at startup; this is the second
    # line of defence so the router cannot be reached even if it ever starts.
    if settings.env == "dev" and settings.storage_backend == "local":
        app.include_router(dev_storage.router, prefix="/v1")
    if settings.env == "dev":
        app.include_router(dev_auth.router, prefix="/v1")
    return app


app = create_app()
