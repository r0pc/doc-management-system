# backend/tests/integration/test_migration_0006.py
"""0006 must not hide the global doc types it did not create.

doc_types was outside RLS. Adding tenant_id plus a naive policy would make
every seeded global type invisible to every tenant.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

pytestmark = [pytest.mark.integration]

TENANT_A = "c0000000-0000-0000-0000-000000000001"


def test_global_doc_types_remain_visible_under_rls(app_role_db: psycopg.Connection) -> None:
    conn = app_role_db
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (TENANT_A,))
    row = conn.execute("SELECT count(*) FROM doc_types WHERE tenant_id IS NULL").fetchone()
    assert row is not None
    assert row[0] > 0, "0006's RLS policy hid the seeded global doc types"


def test_tenant_cannot_see_another_tenants_doc_type(app_role_db: psycopg.Connection) -> None:
    conn = app_role_db
    other = "c0000000-0000-0000-0000-0000000000ff"
    type_name = f"ATenantType-{uuid.uuid4()}"

    # Insert under tenant A
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (TENANT_A,))
    conn.execute(
        "INSERT INTO doc_types (id, parent_id, name, description, tenant_id) "
        "VALUES (gen_random_uuid(), NULL, %s, '', %s)",
        (type_name, TENANT_A),
    )
    conn.commit()

    # Query under tenant B
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (other,))
    found = conn.execute(
        "SELECT count(*) FROM doc_types WHERE name = %s",
        (type_name,),
    ).fetchone()
    assert found is not None
    assert found[0] == 0


@pytest.mark.parametrize("table", ["doc_type_prototypes", "detector_rules"])
def test_new_tables_have_rls_enabled_and_forced(db: psycopg.Connection, table: str) -> None:
    row = db.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
        (table,),
    ).fetchone()
    assert row is not None
    assert row[0] is True, f"{table} does not have RLS enabled (#26)"
    assert row[1] is True, f"{table} does not FORCE RLS (#26)"


def test_prototype_requires_at_least_five_samples(app_role_db: psycopg.Connection) -> None:
    conn = app_role_db
    with pytest.raises(psycopg.Error):
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (TENANT_A,))
        conn.execute(
            "INSERT INTO doc_type_prototypes "
            "(id, tenant_id, doc_type_id, centroid_vector, sample_count) "
            "SELECT gen_random_uuid(), %s, id, "
            "array_fill(0.0::real, ARRAY[384])::vector, 4 FROM doc_types LIMIT 1",
            (TENANT_A,),
        )
        conn.commit()


def test_detector_rule_requires_a_validator(app_role_db: psycopg.Connection) -> None:
    """#10: a bare regex is not an acceptable recogniser."""
    conn = app_role_db
    with pytest.raises(psycopg.Error):
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (TENANT_A,))
        conn.execute(
            "INSERT INTO detector_rules (id, tenant_id, entity_type, pattern, "
            "validator_kind, context_words, level_rank, enabled) VALUES "
            "(gen_random_uuid(), %s, 'x', 'y', NULL, ARRAY['a'], 3, true)",
            (TENANT_A,),
        )
        conn.commit()
