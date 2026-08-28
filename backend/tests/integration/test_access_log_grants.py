"""access_log grants (#24): append/read only - the audit trail is immutable.

The application role must hold INSERT and SELECT on access_log and must NOT
hold UPDATE or DELETE, proven both via has_table_privilege and by behaviour.

access_log is under ENABLE + FORCE ROW LEVEL SECURITY since 0004 (#26), so the
append probe binds ``app.tenant_id`` and writes a matching ``tenant_id`` - the
same path ``deps.record_audit`` takes inside a ``bind_tenant`` block. The grant
assertions below are unaffected by RLS: privilege checks run before policy, so
a denied UPDATE/DELETE still surfaces as InsufficientPrivilege.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

pytestmark = [pytest.mark.integration]


def test_docmgmt_app_cannot_update_or_delete_access_log(app_role_db) -> None:
    conn = app_role_db

    # Given: the declared grant matrix on access_log.
    privileges = {
        action: conn.execute(
            "SELECT has_table_privilege('docmgmt_app', 'access_log', %s)", (action,)
        ).fetchone()[0]
        for action in ("SELECT", "INSERT", "UPDATE", "DELETE")
    }
    # Then: INSERT/SELECT granted; UPDATE/DELETE revoked (#24).
    assert privileges == {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False}

    # Behaviour: appending an audit row works (bigserial sequence grant included).
    # The row must satisfy the tenant_isolation WITH CHECK (#26), so bind the
    # GUC for this transaction and write the same tenant onto the row.
    tenant_id = uuid.uuid4()
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
    conn.execute(
        "INSERT INTO access_log (tenant_id, document_id, actor_id, action, ts)"
        " VALUES (%s, NULL, NULL, 'integration-probe', now())",
        (tenant_id,),
    )
    # And it is readable back through the same tenant lens - not written into a
    # hole the way a NULL tenant_id row would be.
    appended = conn.execute(
        "SELECT count(*) FROM access_log WHERE action = 'integration-probe'"
    ).fetchone()[0]
    assert appended == 1

    # Behaviour: tampering with history is denied at the server.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE access_log SET action = 'tampered'")
    conn.rollback()

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM access_log")
    conn.rollback()
