"""The ENV=prod startup gate: every security control must be configured on.

``validate_runtime`` is the one place a production process proves it was
deployed rather than merely started. Each control below silently degrades a
security invariant if it drifts, so the gate refuses the process instead.
"""

import pytest

from app.config import _BACKEND_DIR, _ENV_FILES, _REPO_ROOT, Settings, validate_runtime


class TestEnvFileDiscovery:
    """Config discovery must not depend on where the process was launched.

    A bare ``env_file=".env"`` resolves against the CWD. The documented
    workflow keeps .env at the repo root and starts the API from backend/, so
    the file was never read and every setting silently fell back to its
    default — including ``env="prod"``, which then tripped the production gate
    on a developer machine. A missing config file must not be able to
    masquerade as a production deployment.
    """

    def test_env_files_are_absolute(self) -> None:
        assert all(path.is_absolute() for path in _ENV_FILES)

    def test_repo_root_is_located_correctly(self) -> None:
        # Anchored, not guessed: these two files pin the layout the paths assume.
        assert (_REPO_ROOT / ".env.example").is_file()
        assert (_BACKEND_DIR / "pyproject.toml").is_file()

    def test_root_env_is_searched_and_backend_env_wins(self) -> None:
        assert _ENV_FILES[0] == _REPO_ROOT / ".env"
        # Later entries take priority in pydantic-settings, so a backend-local
        # override must come last.
        assert _ENV_FILES[-1] == _BACKEND_DIR / ".env"

    def test_suite_never_reads_a_developer_env_file(self) -> None:
        """Whether this suite passes must not depend on whose machine ran it."""
        assert Settings.model_config["env_file"] is None


class TestBlankOidcIsUnset:
    """A blank `.env` line means unset, and must select the dev shim.

    `.env.example` ships `OIDC_ISSUER=` to show the key exists. dotenv reports
    that as "", not None, so an `is None` check treated a blank as a configured
    issuer, skipped the dev JWT verifier, and constructed a JWKS client from an
    empty string. That failed only once a request arrived — a 500 on every
    authenticated endpoint, with a traceback instead of a config error.
    """

    def test_blank_string_normalises_to_none(self) -> None:
        settings = Settings(env="dev", dev_jwt_secret="s3cret-for-tests", oidc_issuer="")  # noqa: S106
        assert settings.oidc_issuer is None

    def test_whitespace_only_normalises_to_none(self) -> None:
        settings = Settings(env="dev", dev_jwt_secret="s3cret-for-tests", oidc_audience="   ")  # noqa: S106
        assert settings.oidc_audience is None

    def test_a_real_issuer_survives(self) -> None:
        settings = Settings(env="dev", dev_jwt_secret="s3cret", oidc_issuer="https://idp/realm")  # noqa: S106
        assert settings.oidc_issuer == "https://idp/realm"

    def test_dev_with_blank_issuer_selects_the_dev_shim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The end-to-end symptom: this is what returned 500 on every request."""
        from app.api.deps import get_verifier
        from app.security.auth import DevJWTVerifier

        monkeypatch.setenv("ENV", "dev")
        monkeypatch.setenv("DEV_JWT_SECRET", "a-dev-secret-value")
        monkeypatch.setenv("OIDC_ISSUER", "")
        get_verifier.cache_clear()
        try:
            assert isinstance(get_verifier(), DevJWTVerifier)
        finally:
            get_verifier.cache_clear()

    def test_prod_rejects_a_schemeless_issuer(self) -> None:
        with pytest.raises(RuntimeError, match="absolute http"):
            validate_runtime(prod_settings(oidc_issuer="idp.internal/realms/docmgmt"))


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
