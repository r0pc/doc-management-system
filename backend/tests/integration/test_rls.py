"""Row-level security (#26): tenant scoping lives in the policy, not a WHERE.

The app role inserts two tenants' data, then proves: scoped visibility per
GUC, cross-tenant writes invisible, and an unset GUC yields zero rows
(fail-closed, because current_setting(..., true) returns NULL).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [pytest.mark.integration]


def _insert_tenant_tree(conn, tenant_id: uuid.UUID, sub: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    """Tenant + department + user + one document, all under the given tenant."""
    department_id = uuid.uuid4()
    user_id = uuid.uuid4()
    document_id = uuid.uuid4()
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
    conn.execute("INSERT INTO tenants (id, name) VALUES (%s, %s)", (tenant_id, f"tenant-{sub}"))
    conn.execute(
        "INSERT INTO departments (id, tenant_id, name) VALUES (%s, %s, 'HQ')",
        (department_id, tenant_id),
    )
    conn.execute(
        "INSERT INTO users (id, tenant_id, department_id, oidc_sub, email, role,"
        " clearance_rank) VALUES (%s, %s, %s, %s, %s, 'employee', 2)",
        (user_id, tenant_id, department_id, sub, f"{sub}@example.test"),
    )
    conn.execute(
        "INSERT INTO documents (id, tenant_id, department_id, original_filename,"
        " status, uploaded_by) VALUES (%s, %s, %s, %s, 'ready', %s)",
        (document_id, tenant_id, department_id, f"{sub}.pdf", user_id),
    )
    return document_id


def test_app_role_sees_only_bound_tenant_and_unset_guc_is_fail_closed(
    app_role_db,
) -> None:
    conn = app_role_db
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    # Given: two tenants' trees inserted by the app role itself.
    doc_a = _insert_tenant_tree(conn, tenant_a, "rls-a")
    doc_b = _insert_tenant_tree(conn, tenant_b, "rls-b")
    conn.commit()

    # When: bound to tenant A. Then: only A's rows are visible.
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_a),))
    assert conn.execute("SELECT count(*) FROM tenants").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
    assert conn.execute("SELECT id FROM documents").fetchone()[0] == doc_a

    # Cross-tenant mutation is invisible -> zero rows affected.
    cur = conn.execute("UPDATE documents SET status = 'held' WHERE tenant_id = %s", (tenant_b,))
    assert cur.rowcount == 0
    assert conn.execute("SELECT count(*) FROM documents WHERE id = %s", (doc_b,)).fetchone()[0] == 0

    # When: rebound to tenant B within the same transaction.
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_b),))
    # Then: only B's rows are visible.
    assert conn.execute("SELECT count(*) FROM tenants").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
    conn.commit()

    # When: a fresh transaction with NO GUC binding.
    # Then: fail-closed - NULL never equals a tenant id, so zero rows.
    assert conn.execute("SELECT count(*) FROM tenants").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
