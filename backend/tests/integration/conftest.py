"""Integration-suite fixtures: real PostgreSQL, real Alembic runs.

Every module here carries ``pytestmark = pytest.mark.integration`` so the
default ``-m "not integration"`` addopts deselects the suite; run it with
``pytest -q -m integration``. The suite targets a reachable PostgreSQL with
the compose dev credentials; set ``DATABASE_URL`` to retarget it (e.g. a
sidecar on another port). Throwaway databases are created per session and
dropped afterwards - nothing outside them is touched.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote, urlparse

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import psycopg
import pytest
from alembic.config import Config
from sqlalchemy import create_engine

from alembic import command

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

BACKEND_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB = "postgresql://docmgmt:docmgmt@localhost:55432/docmgmt"
APP_ROLE = "docmgmt_app"
DEV_PASSWORD = "docmgmt"  # noqa: S105 - documented compose/dev default only


@dataclass(frozen=True, slots=True)
class DbTarget:
    """One PostgreSQL database in both libpq and SQLAlchemy URL forms."""

    host: str
    port: int
    user: str
    password: str
    dbname: str

    @property
    def libpq_url(self) -> str:
        return (
            f"postgresql://{quote(self.user)}:{quote(self.password)}"
            f"@{self.host}:{self.port}/{self.dbname}"
        )

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"postgresql+psycopg://{quote(self.user)}:{quote(self.password)}"
            f"@{self.host}:{self.port}/{self.dbname}"
        )

    def with_dbname(self, dbname: str) -> DbTarget:
        return replace(self, dbname=dbname)


def _parse_admin_target() -> DbTarget:
    raw = os.environ.get("DATABASE_URL", DEFAULT_DB).replace("+psycopg", "")
    parsed = urlparse(raw)
    return DbTarget(
        host=parsed.hostname or "localhost",
        port=parsed.port or 55432,
        user=parsed.username or "docmgmt",
        password=parsed.password or "docmgmt",
        dbname=(parsed.path or "/docmgmt").lstrip("/") or "docmgmt",
    )


class MigrationHarness:
    """Creates/destroys throwaway databases and drives Alembic against them."""

    def __init__(self, admin: DbTarget) -> None:
        self._admin = admin

    def create_database(self, prefix: str = "dms_it") -> DbTarget:
        dbname = f"{prefix}_{secrets.token_hex(6)}"
        with psycopg.connect(self._admin.libpq_url, autocommit=True) as conn:
            conn.execute('CREATE DATABASE "' + dbname + '"')
        return self._admin.with_dbname(dbname)

    def drop_database(self, target: DbTarget) -> None:
        maintenance = self._admin.with_dbname("postgres")
        with psycopg.connect(maintenance.libpq_url, autocommit=True) as conn:
            conn.execute('DROP DATABASE IF EXISTS "' + target.dbname + '" WITH (FORCE)')

    def upgrade(self, target: DbTarget, revision: str) -> None:
        """Run ``alembic upgrade <revision>`` against ``target``.

        env.py prefers a connection injected via ``config.attributes``, so the
        URL override never has to fight ``Settings`` for control.
        """
        self._run(target, command.upgrade, revision)

    def downgrade(self, target: DbTarget, revision: str) -> None:
        """Run ``alembic downgrade <revision>`` against ``target``."""
        self._run(target, command.downgrade, revision)

    def _run(self, target: DbTarget, cmd: Callable[[Config, str], None], revision: str) -> None:
        engine = create_engine(target.sqlalchemy_url)
        try:
            cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
            cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
            cfg.attributes["connection"] = engine
            cmd(cfg, revision)
        finally:
            engine.dispose()


@pytest.fixture(scope="session")
def admin_target() -> DbTarget:
    target = _parse_admin_target()
    with psycopg.connect(target.libpq_url, autocommit=True) as conn:
        conn.execute("SELECT 1")
    return target


@pytest.fixture(scope="session")
def harness(admin_target: DbTarget) -> MigrationHarness:
    return MigrationHarness(admin_target)


@pytest.fixture(scope="session")
def migrated_db(harness: MigrationHarness) -> Iterator[DbTarget]:
    """A throwaway database migrated to head for the whole session."""
    target = harness.create_database()
    harness.upgrade(target, "head")
    try:
        yield target
    finally:
        harness.drop_database(target)


@pytest.fixture()
def db(migrated_db: DbTarget) -> Iterator[psycopg.Connection]:
    """Fresh transactional connection (as the migrator user) to the schema."""
    with psycopg.connect(migrated_db.libpq_url) as conn:
        yield conn
        conn.rollback()


@pytest.fixture()
def app_role_db(migrated_db: DbTarget) -> Iterator[psycopg.Connection]:
    """Connection authenticated as the docmgmt_app role (#24/#26 subject)."""
    url = (
        f"postgresql://{APP_ROLE}:{quote(DEV_PASSWORD)}"
        f"@{migrated_db.host}:{migrated_db.port}/{migrated_db.dbname}"
    )
    with psycopg.connect(url) as conn:
        yield conn
        conn.rollback()
