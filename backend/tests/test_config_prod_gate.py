"""The ENV=prod startup gate: every security control must be configured on.

``validate_runtime`` is the one place a production process proves it was
deployed rather than merely started. Each control below silently degrades a
security invariant if it drifts, so the gate refuses the process instead.
"""

import pytest

from app.config import Settings, validate_runtime

PROD_READY = {
    "env": "prod",
    "scan_enabled": True,
    "storage_backend": "minio",
    "minio_secure": True,
    "minio_secret_key": "a-real-generated-secret",
    "oidc_issuer": "https://idp.internal/realms/docmgmt",
    "dev_jwt_secret": "",
    "cors_origins": ["https://docs.internal"],
}


def prod_settings(**overrides: object) -> Settings:
    return Settings(**{**PROD_READY, **overrides})  # type: ignore[arg-type]


def test_fully_configured_prod_starts() -> None:
    validate_runtime(prod_settings())


def test_dev_is_not_gated() -> None:
    """Dev is deliberately permissive - loopback CORS, local storage, no OIDC."""
    validate_runtime(Settings(env="dev", dev_jwt_secret="a-dev-secret-value"))  # noqa: S106


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"scan_enabled": False}, "SCAN_ENABLED"),
        ({"storage_backend": "local"}, "STORAGE_BACKEND"),
        ({"oidc_issuer": None}, "OIDC_ISSUER"),
        ({"dev_jwt_secret": "leftover-dev-secret"}, "DEV_JWT_SECRET"),
        ({"minio_secret_key": "minioadmin"}, "MINIO_SECRET_KEY"),
        ({"minio_secure": False}, "MINIO_SECURE"),
        ({"cors_origins": ["http://localhost:5173"]}, "CORS_ORIGINS"),
        ({"cors_origins": ["http://127.0.0.1:5173"]}, "CORS_ORIGINS"),
    ],
)
def test_each_control_is_individually_fatal(override: dict[str, object], expected: str) -> None:
    with pytest.raises(RuntimeError, match=expected):
        validate_runtime(prod_settings(**override))


def test_every_violation_is_reported_in_one_pass() -> None:
    """Aggregated, not short-circuited: one restart surfaces the whole set."""
    with pytest.raises(RuntimeError) as excinfo:
        validate_runtime(
            prod_settings(
                scan_enabled=False,
                storage_backend="local",
                oidc_issuer=None,
                minio_secret_key="minioadmin",  # noqa: S106
            )
        )
    message = str(excinfo.value)
    for control in ("SCAN_ENABLED", "STORAGE_BACKEND", "OIDC_ISSUER", "MINIO_SECRET_KEY"):
        assert control in message


def test_dev_storage_router_is_not_mounted_outside_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """The HMAC dev-storage surface is signed with a secret prod does not set.

    Pinned on the exact risky combination: STORAGE_BACKEND defaults to "local",
    so gating the router on the backend alone would mount object read/write
    into a production process.
    """
    from app.main import create_app

    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    paths = set(create_app().openapi()["paths"])

    assert not any("dev-storage" in path for path in paths)
    assert not any("dev/token" in path for path in paths)


def test_dev_storage_router_is_mounted_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Counterpart to the gate above - dev tooling must still work."""
    from app.main import create_app

    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("DEV_JWT_SECRET", "a-dev-secret-value")
    paths = set(create_app().openapi()["paths"])

    assert any("dev-storage" in path for path in paths)
    assert any("dev/token" in path for path in paths)
