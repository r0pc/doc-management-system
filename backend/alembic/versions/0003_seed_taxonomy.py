"""Seed taxonomy and demo tenant: security levels, doc types, demo org.

All identifiers are obviously fake (example.test addresses, dev-* OIDC
subjects, fixed literal UUIDs) per the safety rails - no real personal data.
Fixed UUIDs make downgrade() an exact, surgical reversal by primary key.

ID scheme (hex prefixes chosen to be readable in psql):
- security_levels  a0000000-...-00000000000R   (R = rank 1..4)
- doc_types        b0000000-...-0000000000NN
- tenant           c0000000-...-000000000001
- departments      c0000000-...-00000000001D   (HQ=1, HR=2, Engineering=3)
- users            c0000000-...-00000000010U   (admin..viewer = 1..5)

RLS interaction (why SET LOCAL appears here): 0002 left every tenanted table
under ENABLE + FORCE ROW LEVEL SECURITY (#26). FORCE subjects even non-
superuser table owners to the policies; superusers bypass RLS entirely. This
migration binds ``app.tenant_id`` to the seeded tenant for its whole
transaction so the inserts succeed under EITHER operator kind, and they
travel through exactly the policy path production writes will use. The GUC
is transaction-scoped: it evaporates at commit and cannot leak into later
migrations or sessions.

downgrade() re-binds the same GUC before deleting - with RLS still applied
(this revision downgrades before 0002), the rows are only visible through
the same tenant lens that created them. All SQL below is static: every value
is a compile-time literal, so there is nothing to inject.
"""

from __future__ import annotations

from alembic import op

revision: str = "0003_seed_taxonomy"
down_revision: str | None = "0002_security_hardening"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Bind the RLS tenant for this transaction (see module docstring).
    op.execute("SET LOCAL app.tenant_id = 'c0000000-0000-0000-0000-000000000001'")

    # --- security levels: rank is data, never a key (#23) ---
    op.execute(
        """
        INSERT INTO security_levels (id, rank, name, description) VALUES
            ('a0000000-0000-0000-0000-000000000001', 1, 'Public',
             'Shareable outside the organisation without review.'),
            ('a0000000-0000-0000-0000-000000000002', 2, 'Internal',
             'Default when nothing matches; internal circulation only.'),
            ('a0000000-0000-0000-0000-000000000003', 3, 'Confidential',
             'Sensitive business or personal data; need-to-know access.'),
            ('a0000000-0000-0000-0000-000000000004', 4, 'Restricted',
             'Statutory or regulated identifiers; highest protection.')
        """
    )

    # --- document type hierarchy: parents before children ---
    op.execute(
        """
        INSERT INTO doc_types (id, parent_id, name, description) VALUES
            ('b0000000-0000-0000-0000-000000000001', NULL, 'Contract',
             'Binding agreements.'),
            ('b0000000-0000-0000-0000-000000000003', NULL, 'HR',
             'Human resources records.'),
            ('b0000000-0000-0000-0000-000000000005', NULL, 'Invoice',
             'Billing documents.'),
            ('b0000000-0000-0000-0000-000000000006', NULL, 'Report',
             'Periodic and ad-hoc reports.'),
            ('b0000000-0000-0000-0000-000000000008', NULL, 'Policy Memo',
             'Internal policy announcements.'),
            ('b0000000-0000-0000-0000-000000000002',
             'b0000000-0000-0000-0000-000000000001', 'Vendor MSA',
             'Master service agreements with vendors.'),
            ('b0000000-0000-0000-0000-000000000004',
             'b0000000-0000-0000-0000-000000000003', 'Disciplinary Notice',
             'Formal disciplinary actions.'),
            ('b0000000-0000-0000-0000-000000000007',
             'b0000000-0000-0000-0000-000000000006', 'Monthly Report',
             'Recurring monthly reporting.')
        """
    )

    # --- demo organisation: one tenant, HQ with HR and Engineering children ---
    op.execute(
        """
        INSERT INTO tenants (id, name) VALUES
            ('c0000000-0000-0000-0000-000000000001', 'Demo Tenant')
        """
    )
    op.execute(
        """
        INSERT INTO departments (id, tenant_id, parent_id, name) VALUES
            ('c0000000-0000-0000-0000-000000000011',
             'c0000000-0000-0000-0000-000000000001', NULL, 'HQ'),
            ('c0000000-0000-0000-0000-000000000012',
             'c0000000-0000-0000-0000-000000000001',
             'c0000000-0000-0000-0000-000000000011', 'HR'),
            ('c0000000-0000-0000-0000-000000000013',
             'c0000000-0000-0000-0000-000000000001',
             'c0000000-0000-0000-0000-000000000011', 'Engineering')
        """
    )
    op.execute(
        """
        INSERT INTO users (id, tenant_id, department_id, oidc_sub, email, role,
                           clearance_rank) VALUES
            ('c0000000-0000-0000-0000-000000000101',
             'c0000000-0000-0000-0000-000000000001',
             'c0000000-0000-0000-0000-000000000011',
             'dev-admin', 'admin@example.test', 'admin', 4),
            ('c0000000-0000-0000-0000-000000000102',
             'c0000000-0000-0000-0000-000000000001',
             'c0000000-0000-0000-0000-000000000011',
             'dev-officer', 'officer@example.test', 'security_officer', 4),
            ('c0000000-0000-0000-0000-000000000103',
             'c0000000-0000-0000-0000-000000000001',
             'c0000000-0000-0000-0000-000000000012',
             'dev-manager', 'manager@example.test', 'dept_manager', 3),
            ('c0000000-0000-0000-0000-000000000104',
             'c0000000-0000-0000-0000-000000000001',
             'c0000000-0000-0000-0000-000000000013',
             'dev-employee', 'employee@example.test', 'employee', 2),
            ('c0000000-0000-0000-0000-000000000105',
             'c0000000-0000-0000-0000-000000000001',
             'c0000000-0000-0000-0000-000000000013',
             'dev-viewer', 'viewer@example.test', 'viewer', 1)
        """
    )


def downgrade() -> None:
    # Same tenant lens as upgrade(): RLS from 0002 is still applied here.
    op.execute("SET LOCAL app.tenant_id = 'c0000000-0000-0000-0000-000000000001'")

    op.execute(
        """
        DELETE FROM users WHERE id IN (
            'c0000000-0000-0000-0000-000000000101',
            'c0000000-0000-0000-0000-000000000102',
            'c0000000-0000-0000-0000-000000000103',
            'c0000000-0000-0000-0000-000000000104',
            'c0000000-0000-0000-0000-000000000105'
        )
        """
    )
    # Children before the HQ parent (self-referential FK on departments).
    op.execute(
        """
        DELETE FROM departments WHERE id IN (
            'c0000000-0000-0000-0000-000000000012',
            'c0000000-0000-0000-0000-000000000013'
        )
        """
    )
    op.execute("DELETE FROM departments WHERE id = 'c0000000-0000-0000-0000-000000000011'")
    op.execute("DELETE FROM tenants WHERE id = 'c0000000-0000-0000-0000-000000000001'")

    # Children before parents (self-referential FK on doc_types).
    op.execute(
        """
        DELETE FROM doc_types WHERE id IN (
            'b0000000-0000-0000-0000-000000000002',
            'b0000000-0000-0000-0000-000000000004',
            'b0000000-0000-0000-0000-000000000007'
        )
        """
    )
    op.execute(
        """
        DELETE FROM doc_types WHERE id IN (
            'b0000000-0000-0000-0000-000000000001',
            'b0000000-0000-0000-0000-000000000003',
            'b0000000-0000-0000-0000-000000000005',
            'b0000000-0000-0000-0000-000000000006',
            'b0000000-0000-0000-0000-000000000008'
        )
        """
    )
    op.execute(
        """
        DELETE FROM security_levels WHERE id IN (
            'a0000000-0000-0000-0000-000000000001',
            'a0000000-0000-0000-0000-000000000002',
            'a0000000-0000-0000-0000-000000000003',
            'a0000000-0000-0000-0000-000000000004'
        )
        """
    )
