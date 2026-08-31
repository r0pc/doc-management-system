"""add detail column to access_log

Revision ID: d7d1c3d1c60b
Revises: 0005_monotonic_audit_backfill
Create Date: 2026-08-31 23:32:45.706437

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7d1c3d1c60b"
down_revision: str | None = "0005_monotonic_audit_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("access_log", sa.Column("detail", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("access_log", "detail")
