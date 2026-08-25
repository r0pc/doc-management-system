"""The check_monotonic trigger (#8), exercised against real PostgreSQL.

Automated reclassification (decided_by in 'rules'/'ml') must never lower the
security level; a human decision may. Every sub-case runs in its own
transaction and rolls back - the seeded baseline is committed once.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import psycopg
import pytest

pytestmark = [pytest.mark.integration]

LOWER_MESSAGE = "automated reclassification cannot lower security level"


@dataclass(frozen=True, slots=True)
class Seed:
    """Identifiers of one seeded document tree, plus the level lookup."""

    tenant: uuid.UUID
    document: uuid.UUID
    version: uuid.UUID
    levels: dict[str, uuid.UUID]


def _seed_document_with_internal(conn: psycopg.Connection) -> Seed:
    """One tenant/department/user/blob/document/version plus an Internal rules row."""
    seed = Seed(
        tenant=uuid.uuid4(),
        document=uuid.uuid4(),
        version=uuid.uuid4(),
        levels={},
    )
    department_id = uuid.uuid4()
    user_id = uuid.uuid4()
    blob_sha = "it-" + "0" * 58
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(seed.tenant),))
    conn.execute("INSERT INTO tenants (id, name) VALUES (%s, 'rls-it-tenant')", (seed.tenant,))
    conn.execute(
        "INSERT INTO departments (id, tenant_id, name) VALUES (%s, %s, 'IT')",
        (department_id, seed.tenant),
    )
    conn.execute(
        "INSERT INTO users (id, tenant_id, department_id, oidc_sub, email, role,"
        " clearance_rank) VALUES (%s, %s, %s, 'it-seed-sub', 'seed@example.test',"
        " 'employee', 2)",
        (user_id, seed.tenant, department_id),
    )
    conn.execute(
        "INSERT INTO blobs (sha256, size_bytes, mime_sniffed, bucket_key)"
        " VALUES (%s, 1, 'application/pdf', 'q/x')",
        (blob_sha,),
    )
    conn.execute(
        "INSERT INTO documents (id, tenant_id, department_id, original_filename,"
        " status, uploaded_by) VALUES (%s, %s, %s, 'seed.pdf', 'ready', %s)",
        (seed.document, seed.tenant, department_id, user_id),
    )
    conn.execute(
        "INSERT INTO document_versions (id, document_id, blob_sha256, version_no,"
        " created_by) VALUES (%s, %s, %s, 1, %s)",
        (seed.version, seed.document, blob_sha, user_id),
    )
    seed.levels.update(conn.execute("SELECT name, id FROM security_levels").fetchall())
    assert set(seed.levels) == {"Public", "Internal", "Confidential", "Restricted"}
    conn.execute(
        "INSERT INTO classifications (id, document_id, version_id, level_id,"
        " decided_by) VALUES (%s, %s, %s, %s, 'rules')",
        (uuid.uuid4(), seed.document, seed.version, seed.levels["Internal"]),
    )
    return seed


def _insert_classification(
    conn: psycopg.Connection, seed: Seed, level_name: str, decided_by: str
) -> None:
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(seed.tenant),))
    conn.execute(
        "INSERT INTO classifications (id, document_id, version_id, level_id,"
        " decided_by) VALUES (%s, %s, %s, %s, %s)",
        (
            uuid.uuid4(),
            seed.document,
            seed.version,
            seed.levels[level_name],
            decided_by,
        ),
    )


def test_automated_lowering_blocked_human_allowed_higher_allowed(db) -> None:
    # Given: a document whose current classification is Internal by 'rules'.
    seed = _seed_document_with_internal(db)
    db.commit()

    # When/Then: automated ('ml') lowering to Public raises the spec message.
    with pytest.raises(psycopg.errors.RaiseException, match=LOWER_MESSAGE):
        _insert_classification(db, seed, "Public", "ml")
    db.rollback()

    # A human may lower the level; that write is the audited path.
    _insert_classification(db, seed, "Public", "human")
    db.rollback()

    # Automated equal-or-higher decisions pass the trigger.
    _insert_classification(db, seed, "Confidential", "ml")
    db.rollback()
