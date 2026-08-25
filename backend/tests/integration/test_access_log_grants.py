"""access_log grants (#24): append/read only - the audit trail is immutable.

The application role must hold INSERT and SELECT on access_log and must NOT
hold UPDATE or DELETE, proven both via has_table_privilege and by behaviour.
"""

from __future__ import annotations

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
    conn.execute(
        "INSERT INTO access_log (document_id, actor_id, action, ts)"
        " VALUES (NULL, NULL, 'integration-probe', now())"
    )

    # Behaviour: tampering with history is denied at the server.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE access_log SET action = 'tampered'")
    conn.rollback()

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM access_log")
    conn.rollback()
