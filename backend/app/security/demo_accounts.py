# ruff: noqa: S106 -- the literal passwords below ARE the feature: they are
# published by GET /v1/auth/demo-accounts and printed on the login page. See
# the module docstring for why hashing them would be theatre.

"""The five demo identities: one per role, spanning all four security levels.

These mirror the users seeded by migration ``0003_seed_taxonomy`` exactly — same
``oidc_sub``, email, role and ``clearance_rank``. The alignment is the whole
point. :func:`app.api.deps.provision_actor` upserts on ``oidc_sub``, so a
subject that does not match the seed does not sign in as the seeded user: it
silently provisions a SECOND row with a synthesised ``…@oidc.local`` email. The
dev persona shim has been doing precisely that (``dev-admin_t1`` vs
``dev-admin``), which is why the seeded rows were dead weight.

Passwords are plaintext constants, deliberately. They are printed on the login
page beside the form, the endpoint that checks them refuses to mount outside
``env="dev"``, and ``users`` carries no password column in any environment.
Hashing a credential that is displayed next to the field it unlocks would be
theatre. Production authenticates through OIDC (AGENTS.md:197) and never
reaches this module.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.domain.models import LEVEL_RANK, LevelName

#: The demo tenant and departments created by migration 0003.
DEMO_TENANT_ID: Final = UUID("c0000000-0000-0000-0000-000000000001")
_HQ: Final = UUID("c0000000-0000-0000-0000-000000000011")
_HR: Final = UUID("c0000000-0000-0000-0000-000000000012")
_ENGINEERING: Final = UUID("c0000000-0000-0000-0000-000000000013")

_RANK_TO_LEVEL: Final[dict[int, str]] = {rank: level.value for level, rank in LEVEL_RANK.items()}


@dataclass(frozen=True, slots=True)
class DemoAccount:
    """One demo identity. Frozen: the login path must not be able to edit it."""

    oidc_sub: str
    email: str
    password: str
    display_name: str
    role: str
    clearance_rank: int
    department_id: UUID
    department_label: str
    tenant_id: UUID = DEMO_TENANT_ID

    @property
    def level_name(self) -> str:
        """The security level this clearance rank corresponds to."""
        return _RANK_TO_LEVEL[self.clearance_rank]


DEMO_ACCOUNTS: Final[tuple[DemoAccount, ...]] = (
    DemoAccount(
        oidc_sub="dev-admin",
        email="admin@example.test",
        password="demo-admin",
        display_name="Alice Ahmed",
        role="admin",
        clearance_rank=LEVEL_RANK[LevelName.RESTRICTED],
        department_id=_HQ,
        department_label="HQ",
    ),
    DemoAccount(
        oidc_sub="dev-officer",
        email="officer@example.test",
        password="demo-officer",
        display_name="Bilal Officer",
        role="security_officer",
        clearance_rank=LEVEL_RANK[LevelName.RESTRICTED],
        department_id=_HQ,
        department_label="HQ",
    ),
    DemoAccount(
        oidc_sub="dev-manager",
        email="manager@example.test",
        password="demo-manager",
        display_name="Dania Manager",
        role="dept_manager",
        clearance_rank=LEVEL_RANK[LevelName.CONFIDENTIAL],
        department_id=_HR,
        department_label="HR",
    ),
    DemoAccount(
        oidc_sub="dev-employee",
        email="employee@example.test",
        password="demo-employee",
        display_name="Chaudhry Employee",
        role="employee",
        clearance_rank=LEVEL_RANK[LevelName.INTERNAL],
        department_id=_ENGINEERING,
        department_label="Engineering",
    ),
    DemoAccount(
        oidc_sub="dev-viewer",
        email="viewer@example.test",
        password="demo-viewer",
        display_name="Erum Viewer",
        role="viewer",
        clearance_rank=LEVEL_RANK[LevelName.PUBLIC],
        department_id=_ENGINEERING,
        department_label="Engineering",
    ),
)

_BY_EMAIL: Final[dict[str, DemoAccount]] = {a.email: a for a in DEMO_ACCOUNTS}

# Compared against when the email is unknown, so a miss costs the same work as
# a wrong password. Length matches the real ones; compare_digest leaks length,
# not content.
_DECOY_PASSWORD: Final = "x" * max(len(a.password) for a in DEMO_ACCOUNTS)


def authenticate(email: str, password: str) -> DemoAccount | None:
    """Return the account these credentials unlock, or None.

    Both branches perform one constant-time comparison so the response does not
    distinguish "no such account" from "wrong password" by timing — the same
    reason the route returns one message for both (#31's shape, applied to
    identities instead of documents).
    """
    account = _BY_EMAIL.get(email.strip().lower())
    reference = account.password if account is not None else _DECOY_PASSWORD
    matched = secrets.compare_digest(password, reference)
    return account if (matched and account is not None) else None


__all__ = ["DEMO_ACCOUNTS", "DEMO_TENANT_ID", "DemoAccount", "authenticate"]
