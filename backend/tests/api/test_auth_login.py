"""Demo sign-in: credentials in, a dev JWT out — and only ever in dev.

Two properties carry real weight here.

The first is that the token's ``sub`` matches the ``oidc_sub`` seeded by
migration 0003. ``provision_actor`` upserts on that column, so a mismatch does
not fail: it quietly provisions a *second* user row with a synthesised
``…@oidc.local`` email and leaves the seeded row untouched. The persona shim has
been doing exactly that. Nothing surfaces the divergence at runtime, so it is
asserted here.

The second is that neither the body nor the code distinguishes an unknown email
from a wrong password. That is #31's reasoning applied to identities: a caller
must not be able to enumerate who exists.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import auth as auth_module
from app.domain.models import LEVEL_RANK
from app.security.auth import DevJWTVerifier
from app.security.demo_accounts import DEMO_ACCOUNTS, authenticate

LOGIN = "/v1/auth/login"
ACCOUNTS = "/v1/auth/demo-accounts"

_SECRET = "unit-test-secret-not-the-compose-default"  # noqa: S105
_AUDIENCE = "docmgmt-api"


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings that make this a dev process. Settings() reads the environment."""
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DEV_JWT_SECRET", _SECRET)


@pytest.fixture
def client(dev_env: None) -> TestClient:
    """The real app, built after the env is dev so the router is mounted."""
    from app.main import create_app

    return TestClient(create_app())


def _login(client: TestClient, email: str, password: str) -> Any:
    return client.post(LOGIN, json={"email": email, "password": password})


class TestSuccessfulLogin:
    @pytest.mark.parametrize("account", DEMO_ACCOUNTS, ids=lambda a: a.role)
    def test_every_demo_account_can_sign_in(self, client: TestClient, account: Any) -> None:
        response = _login(client, account.email, account.password)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["token_type"] == "bearer"  # noqa: S105 -- a scheme name
        assert body["user"]["role"] == account.role
        assert body["user"]["clearance_rank"] == account.clearance_rank

    @pytest.mark.parametrize("account", DEMO_ACCOUNTS, ids=lambda a: a.role)
    def test_token_subject_is_the_seeded_oidc_sub(self, client: TestClient, account: Any) -> None:
        """The regression: a wrong sub silently duplicates the user row."""
        token = _login(client, account.email, account.password).json()["access_token"]
        claims = DevJWTVerifier(_SECRET, env="dev", audience=_AUDIENCE).verify(token)
        assert claims.sub == account.oidc_sub

    @pytest.mark.parametrize("account", DEMO_ACCOUNTS, ids=lambda a: a.role)
    def test_token_carries_the_accounts_authority(self, client: TestClient, account: Any) -> None:
        """Claims are authoritative for role/clearance, so they must be right."""
        token = _login(client, account.email, account.password).json()["access_token"]
        ctx = DevJWTVerifier(_SECRET, env="dev", audience=_AUDIENCE).verify(token)
        assert ctx.role == account.role
        assert ctx.clearance_rank == account.clearance_rank
        assert ctx.tenant_id == account.tenant_id
        assert ctx.department_id == account.department_id

    def test_the_token_expires(self, client: TestClient) -> None:
        account = DEMO_ACCOUNTS[0]
        body = _login(client, account.email, account.password).json()
        assert body["expires_in"] == auth_module.SESSION_TTL_SECONDS
        claims = jwt.decode(body["access_token"], _SECRET, algorithms=["HS256"], audience=_AUDIENCE)
        assert claims["exp"] - claims["iat"] == auth_module.SESSION_TTL_SECONDS

    def test_email_is_matched_case_insensitively_and_trimmed(self, client: TestClient) -> None:
        account = DEMO_ACCOUNTS[0]
        response = _login(client, f"  {account.email.upper()} ", account.password)
        assert response.status_code == 200


class TestRejection:
    def test_wrong_password_is_401(self, client: TestClient) -> None:
        account = DEMO_ACCOUNTS[0]
        assert _login(client, account.email, "not-the-password").status_code == 401

    def test_unknown_email_is_401(self, client: TestClient) -> None:
        assert _login(client, "nobody@example.test", "whatever").status_code == 401

    def test_both_rejections_are_byte_identical(self, client: TestClient) -> None:
        """Anything that differs here enumerates which accounts exist."""
        wrong_password = _login(client, DEMO_ACCOUNTS[0].email, "not-the-password")
        unknown_email = _login(client, "nobody@example.test", "not-the-password")
        assert wrong_password.status_code == unknown_email.status_code
        assert wrong_password.content == unknown_email.content

    def test_another_accounts_password_does_not_work(self, client: TestClient) -> None:
        """Guards against a lookup that checks the password against any account."""
        assert _login(client, DEMO_ACCOUNTS[4].email, DEMO_ACCOUNTS[0].password).status_code == 401

    @pytest.mark.parametrize("payload", [{}, {"email": "a@b.test"}, {"password": "x"}])
    def test_incomplete_bodies_are_rejected(self, client: TestClient, payload: dict) -> None:
        # 400, not FastAPI's default 422: this app maps validation failures onto
        # its problem envelope (tests/api/test_error_envelope.py).
        assert client.post(LOGIN, json=payload).status_code == 400

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_credentials_never_authenticate(self, client: TestClient, blank: str) -> None:
        assert _login(client, blank, blank).status_code in (400, 401)

    def test_a_rejected_body_never_echoes_the_password(self, client: TestClient) -> None:
        """The envelope drops the input; a password field makes that load-bearing."""
        response = client.post(LOGIN, json={"email": "a@b.test", "password": "hunter2-secret"})
        assert "hunter2-secret" not in response.text

    def test_no_token_is_issued_on_failure(self, client: TestClient) -> None:
        body = _login(client, DEMO_ACCOUNTS[0].email, "wrong").json()
        assert "access_token" not in str(body)


class TestDemoAccountListing:
    def test_lists_one_account_per_role(self, client: TestClient) -> None:
        rows = client.get(ACCOUNTS).json()
        assert len(rows) == len(DEMO_ACCOUNTS)
        assert {r["role"] for r in rows} == {
            "admin",
            "security_officer",
            "dept_manager",
            "employee",
            "viewer",
        }

    def test_covers_every_security_level(self, client: TestClient) -> None:
        """The stated requirement: one demo account per security level."""
        rows = client.get(ACCOUNTS).json()
        assert {r["clearance_rank"] for r in rows} == set(LEVEL_RANK.values())
        assert {r["level_name"] for r in rows} == {level.value for level in LEVEL_RANK}

    def test_every_listed_credential_actually_works(self, client: TestClient) -> None:
        """The page prints these; a stale one is a broken demo."""
        for row in client.get(ACCOUNTS).json():
            assert _login(client, row["email"], row["password"]).status_code == 200, row["email"]


class TestDevOnly:
    """The gate is the reason publishing passwords is acceptable at all."""

    def test_router_is_not_mounted_outside_dev(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.delenv("DEV_JWT_SECRET", raising=False)
        from app.main import create_app

        routes = {getattr(r, "path", "") for r in create_app().routes}
        assert LOGIN not in routes
        assert ACCOUNTS not in routes

    @pytest.mark.parametrize("path", [LOGIN, ACCOUNTS])
    def test_handlers_refuse_even_if_mounted_outside_dev(
        self, monkeypatch: pytest.MonkeyPatch, path: str
    ) -> None:
        """Defence in depth: a mis-wired mount must not authenticate anyone."""
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.delenv("DEV_JWT_SECRET", raising=False)
        app = FastAPI()
        app.include_router(auth_module.router, prefix="/v1")
        rogue = TestClient(app)

        response = (
            rogue.post(
                path, json={"email": DEMO_ACCOUNTS[0].email, "password": DEMO_ACCOUNTS[0].password}
            )
            if path == LOGIN
            else rogue.get(path)
        )
        assert response.status_code == 404


class TestSeedAlignment:
    """DEMO_ACCOUNTS must mirror migration 0003, or sign-in duplicates users.

    Nothing at runtime compares the two — the mismatch shows up only as an
    extra row in `users` — so the comparison lives here.
    """

    @staticmethod
    def _seeded_users() -> dict[str, tuple[str, str, int]]:
        migration = (
            Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0003_seed_taxonomy.py"
        ).read_text(encoding="utf-8")
        # Collapse the SQL's line breaks so one pattern spans a whole tuple.
        flat = re.sub(r"\s+", " ", migration)
        rows = re.findall(
            r"'(dev-[a-z]+)', '([^']+)', '([a-z_]+)', (\d+)\)",
            flat,
        )
        return {sub: (email, role, int(rank)) for sub, email, role, rank in rows}

    def test_the_migration_still_seeds_five_users(self) -> None:
        assert len(self._seeded_users()) == len(DEMO_ACCOUNTS)

    @pytest.mark.parametrize("account", DEMO_ACCOUNTS, ids=lambda a: a.role)
    def test_account_matches_its_seeded_row(self, account: Any) -> None:
        seeded = self._seeded_users()
        assert account.oidc_sub in seeded, (
            f"{account.email} has no row in migration 0003; signing in would "
            f"provision a duplicate user instead of using the seeded one"
        )
        assert seeded[account.oidc_sub] == (
            account.email,
            account.role,
            account.clearance_rank,
        )


class TestAuthenticateHelper:
    def test_returns_none_for_an_unknown_email(self) -> None:
        assert authenticate("nobody@example.test", "x") is None

    def test_returns_none_for_a_wrong_password(self) -> None:
        assert authenticate(DEMO_ACCOUNTS[0].email, "x") is None

    def test_passwords_are_distinct(self) -> None:
        """A shared password would make the per-role demo meaningless."""
        assert len({a.password for a in DEMO_ACCOUNTS}) == len(DEMO_ACCOUNTS)
