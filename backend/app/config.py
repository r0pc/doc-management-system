"""Application settings, parsed once from the environment at the boundary.

Every other module receives a `Settings` instance; nothing re-reads os.environ.
Self-hosting invariant: no hosted/cloud service endpoints exist here by design.
"""

from __future__ import annotations

from typing import Final, Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Frozen after construction."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    env: Literal["dev", "prod"] = "prod"
    database_url: str = "postgresql+psycopg://docmgmt:docmgmt@localhost:55432/docmgmt"
    redis_url: str = "redis://localhost:6379/0"

    storage_backend: Literal["local", "minio"] = "local"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"  # noqa: S105 - compose/dev default
    minio_secure: bool = False
    minio_bucket_prefix: str = "docs-"

    scan_enabled: bool = False
    clamav_host: str = "clamav"
    clamav_port: int = 3310

    model_artifact_path: str = "var/models/model.joblib"

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    dev_jwt_secret: str = ""
    oidc_issuer: str | None = None
    oidc_audience: str | None = None

    upload_max_bytes: int = 104857600
    presign_ttl_seconds: int = 90

    @model_validator(mode="after")
    def _validate_dev_jwt_secret(self) -> Self:
        if self.env == "dev" and (
            not self.dev_jwt_secret or self.dev_jwt_secret == "dev-only-secret-change-me"  # noqa: S105
        ):
            raise ValueError(
                "DEV_JWT_SECRET must be explicitly set to a strong secret in dev environment"
            )
        return self

    @field_validator("presign_ttl_seconds")
    @classmethod
    def _clamp_presign_ttl(cls, value: int) -> int:
        """Presigned URLs must stay within the 60-120s policy window."""
        return max(60, min(120, value))

    @property
    def sync_db_url(self) -> str:
        """Sync-engine URL derived from database_url.

        psycopg3 drives both sync and async engines under the same
        `postgresql+psycopg://` dialect; normalising away any async-only
        dialect keeps Alembic and Celery-side engines on one string.
        """
        return self.database_url.replace("+asyncpg", "+psycopg")


# Credentials shipped in .env.example / docker-compose.yml. Reaching production
# with any of these still in place means the deployment was never configured.
_COMPOSE_DEFAULT_SECRETS: Final[frozenset[str]] = frozenset(
    {"minioadmin", "docmgmt", "change-me-to-something-random", "dev-only-secret-change-me"}
)


def _prod_violations(settings: Settings) -> list[str]:
    """Every production misconfiguration, collected rather than short-circuited.

    Reported as one aggregated failure so an operator fixes the whole set in a
    single pass instead of rediscovering them one restart at a time.
    """
    problems: list[str] = []
    if not settings.scan_enabled:
        problems.append("SCAN_ENABLED must be true (malware scanning is fail-closed)")
    # The local backend signs its own presigned URLs with an HMAC dev secret and
    # is served by the /v1/dev-storage router; neither is an authentication
    # boundary. Object storage in prod means a real S3/MinIO backend.
    if settings.storage_backend == "local":
        problems.append("STORAGE_BACKEND=local is dev-only; use minio in prod")
    # #7: identity must come from the OIDC/JWKS path. Without an issuer there is
    # no verifier to build, and the dev HS256 shim must never be reachable.
    if not settings.oidc_issuer:
        problems.append("OIDC_ISSUER is required (the dev JWT shim is forbidden in prod)")
    if settings.dev_jwt_secret:
        problems.append("DEV_JWT_SECRET must be unset in prod")
    if settings.minio_secret_key in _COMPOSE_DEFAULT_SECRETS:
        problems.append("MINIO_SECRET_KEY is still the compose default")
    if not settings.minio_secure and settings.storage_backend == "minio":
        problems.append("MINIO_SECURE must be true in prod (object traffic must be TLS)")
    if any("localhost" in origin or "127.0.0.1" in origin for origin in settings.cors_origins):
        problems.append("CORS_ORIGINS still contains a loopback origin")
    return problems


def validate_runtime(settings: Settings) -> None:
    """Fail-closed startup gate for production processes.

    Dev deployments are deliberately permissive; prod must prove it was
    configured. Anything here would otherwise degrade a security control
    silently at runtime, so it is refused at startup instead.
    """
    if settings.env != "prod":
        return
    problems = _prod_violations(settings)
    if problems:
        joined = "\n  - ".join(problems)
        msg = f"refusing to start with ENV=prod:\n  - {joined}"
        raise RuntimeError(msg)
