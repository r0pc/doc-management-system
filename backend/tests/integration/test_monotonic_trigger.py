"""The check_monotonic trigger (#8), exercised against real PostgreSQL.

Automated reclassification (decided_by in 'rules'/'ml') must never lower the
security level; a human decision may. Every sub-case runs in its own
transaction and rolls back - the seeded baseline is committed once.

The comparison is against the document's CURRENT classification
(``documents.current_classification_id``), narrowed there by 0004 so that an
automated writer may re-agree with a level a human has already lowered. 0005
removed 0004's extra version-equality guard, which let an automated writer
lower the level whenever it named a different version.
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
    next_version: uuid.UUID
    levels: dict[str, uuid.UUID]


def _seed_document_with_internal(conn: psycopg.Connection) -> Seed:
    """One tenant/department/user/blob/document/version plus an Internal rules row."""
    seed = Seed(
        tenant=uuid.uuid4(),
        document=uuid.uuid4(),
        version=uuid.uuid4(),
        next_version=uuid.uuid4(),
        levels={},
    )
    department_id = uuid.uuid4()
    user_id = uuid.uuid4()
    # Unique per seed: several tests seed their own tree into the same
    # session-scoped database, and blobs/users carry unique keys.
    nonce = uuid.uuid4().hex
    blob_sha = "it" + nonce + "0" * 30
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(seed.tenant),))
    conn.execute("INSERT INTO tenants (id, name) VALUES (%s, 'rls-it-tenant')", (seed.tenant,))
    conn.execute(
        "INSERT INTO departments (id, tenant_id, name) VALUES (%s, %s, 'IT')",
        (department_id, seed.tenant),
    )
    conn.execute(
        "INSERT INTO users (id, tenant_id, department_id, oidc_sub, email, role,"
        " clearance_rank) VALUES (%s, %s, %s, %s, %s, 'employee', 2)",
        (user_id, seed.tenant, department_id, f"it-seed-{nonce}", f"{nonce}@example.test"),
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
    # A second version of the same document: the classifier runs per version,
    # so this is the shape 0004's version-equality guard silently exempted.
    conn.execute(
        "INSERT INTO document_versions (id, document_id, blob_sha256, version_no,"
        " created_by) VALUES (%s, %s, %s, 2, %s)",
        (seed.next_version, seed.document, blob_sha, user_id),
    )
    seed.levels.update(conn.execute("SELECT name, id FROM security_levels").fetchall())
    assert set(seed.levels) == {"Public", "Internal", "Confidential", "Restricted"}
    classification_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO classifications (id, document_id, version_id, level_id,"
        " decided_by) VALUES (%s, %s, %s, %s, 'rules')",
        (classification_id, seed.document, seed.version, seed.levels["Internal"]),
    )
    # The trigger compares against documents.current_classification_id, so the
    # seed has to point the document at its classification exactly as the write
    # paths do (app/api/v1/documents.py and app/workers/jobs.py both set it).
    # The FK is DEFERRABLE INITIALLY DEFERRED (#22), so this ordering is legal.
    conn.execute(
        "UPDATE documents SET current_classification_id = %s WHERE id = %s",
        (classification_id, seed.document),
    )
    return seed


def _insert_classification(
    conn: psycopg.Connection,
    seed: Seed,
    level_name: str,
    decided_by: str,
    version_id: uuid.UUID | None = None,
) -> None:
    conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(seed.tenant),))
    conn.execute(
        "INSERT INTO classifications (id, document_id, version_id, level_id,"
        " decided_by) VALUES (%s, %s, %s, %s, %s)",
        (
            uuid.uuid4(),
            seed.document,
            version_id or seed.version,
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


def test_automated_lowering_blocked_on_a_different_version(db) -> None:
    """0004's version-equality guard let a new version carry the level down.

    The document's current classification is Internal on version 1. An
    automated writer classifying version 2 as Public is still an automated
    downgrade of the document (#8), and must be refused.
    """
    seed = _seed_document_with_internal(db)
    db.commit()

    with pytest.raises(psycopg.errors.RaiseException, match=LOWER_MESSAGE):
        _insert_classification(db, seed, "Public", "ml", version_id=seed.next_version)
    db.rollback()

    # The same write by a human is the audited lowering path, and is allowed.
    _insert_classification(db, seed, "Public", "human", version_id=seed.next_version)
    db.rollback()
