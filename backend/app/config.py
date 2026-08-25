"""Application settings, parsed once from the environment at the boundary.

Every other module receives a `Settings` instance; nothing re-reads os.environ.
Self-hosting invariant: no hosted/cloud service endpoints exist here by design.
"""

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Frozen after construction."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    env: Literal["dev", "prod"] = "dev"
    database_url: str = "postgresql+psycopg://docmgmt:docmgmt@localhost:5432/docmgmt"
    redis_url: str = "redis://localhost:6379/0"

    storage_backend: Literal["local", "minio"] = "local"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"  # noqa: S105 - compose/dev default
    minio_secure: bool = False
    minio_bucket_prefix: str = "docs-"

    scan_enabled: bool = False
    dev_jwt_secret: str = "dev-only-secret-change-me"  # noqa: S105 - dev shim only
    oidc_issuer: str | None = None
    oidc_audience: str | None = None

    upload_max_bytes: int = 104857600
    presign_ttl_seconds: int = 90

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


def validate_runtime(settings: Settings) -> None:
    """Fail-closed guard: malware scanning is mandatory outside dev."""
    if settings.env == "prod" and not settings.scan_enabled:
        msg = "SCAN_ENABLED must be true when ENV=prod (fail-closed startup)"
        raise RuntimeError(msg)
