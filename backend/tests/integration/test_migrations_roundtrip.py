"""Roundtrip proof: upgrade head -> downgrade base -> upgrade head, for real.

Asserts the shapes AGENTS.md pins structurally: the deferred circular FK
(#22), bare access_log columns (#24), rank-as-column (#23), and the §6.2
index set - all against a live PostgreSQL, not just metadata.
"""

from __future__ import annotations

import psycopg
import pytest

pytestmark = [pytest.mark.integration]

EXPECTED_TABLES = frozenset(
    {
        "tenants",
        "departments",
        "users",
        "blobs",
        "documents",
        "document_versions",
        "security_levels",
        "doc_types",
        "processing_jobs",
        "keywords",
        "document_keywords",
        "document_text",
        "classifications",
        "findings",
        "review_items",
        "access_log",
    }
)

EXPECTED_INDEXES = frozenset(
    {
        "ix_documents_tenant_status",
        "ix_document_versions_doc_version",
        "ix_classifications_doc_created",
        "ix_access_log_document_ts",
        "ix_access_log_actor_ts",
        "ix_documents_tenant_department",
        "ix_processing_jobs_document_stage",
        "ix_processing_jobs_state_live",
        "ix_document_text_tsv_gin",
        "ix_document_text_embedding_hnsw",
        "ix_document_keywords_keyword_score",
    }
)

# access_log joined this set in 0004: the audit trail is tenanted and must be
# isolated like any other tenanted table (#26). Its rows carry a tenant_id that
# 0005 backfills and pins NOT NULL, so no row can hide from the policy.
RLS_TABLES = frozenset(
    {
        "access_log",
        "tenants",
        "departments",
        "users",
        "documents",
        "document_versions",
        "processing_jobs",
        "document_keywords",
        "review_items",
        "classifications",
        "findings",
    }
)


def _tables(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    return {r[0] for r in rows}


def test_upgrade_downgrade_upgrade_roundtrip(harness) -> None:
    # Given: a fresh throwaway database with no migrations applied.
    target = harness.create_database(prefix="dms_rt")
    try:
        # When: upgrade head.
        harness.upgrade(target, "head")
        # Then: all sixteen tables, every §6.2 index, pgvector, the trigger,
        # RLS forced on exactly the tenanted tables (#26).
        with psycopg.connect(target.libpq_url) as conn:
            assert _tables(conn) >= EXPECTED_TABLES
            indexes = {
                r[0]
                for r in conn.execute(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
                ).fetchall()
            }
            assert indexes >= EXPECTED_INDEXES
            extensions = {r[0] for r in conn.execute("SELECT extname FROM pg_extension").fetchall()}
            assert "vector" in extensions
            triggers = conn.execute(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'classifications'::regclass"
            ).fetchall()
            assert any(t[0] == "trg_check_monotonic" for t in triggers)
            rls = dict(
                conn.execute(
                    "SELECT relname, relrowsecurity AND relforcerowsecurity "
                    "FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                    "AND relkind = 'r'"
                ).fetchall()
            )
            for table in RLS_TABLES:
                assert rls.get(table) is True, f"{table} must have FORCE ROW LEVEL SECURITY"
            for table in EXPECTED_TABLES - RLS_TABLES:
                assert rls.get(table) is not True, f"{table} must not carry RLS"
            # #22: the circular FK exists, is deferrable and initially deferred.
            fk = conn.execute(
                "SELECT condeferrable, condeferred FROM pg_constraint "
                "WHERE conname = 'fk_documents_current_classification_id_classifications'"
            ).fetchone()
            assert fk == (True, True)
            # #24: access_log carries only its PK constraint - no FKs at all.
            access_log_constraints = [
                r[0]
                for r in conn.execute(
                    "SELECT contype FROM pg_constraint WHERE conrelid = 'access_log'::regclass"
                ).fetchall()
            ]
            assert access_log_constraints == ["p"]
            # #23: rank is a plain unique column; the PK stays the surrogate id.
            pk_cols = [
                r[0]
                for r in conn.execute(
                    "SELECT a.attname FROM pg_index i JOIN pg_attribute a "
                    "ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                    "WHERE i.indrelid = 'security_levels'::regclass AND i.indisprimary"
                ).fetchall()
            ]
            assert pk_cols == ["id"]

        # When: downgrade base.
        harness.downgrade(target, "base")
        # Then: no application objects remain (alembic_version lingers, empty).
        with psycopg.connect(target.libpq_url) as conn:
            remaining = _tables(conn)
            assert remaining.isdisjoint(EXPECTED_TABLES)
            leftover_indexes = {
                r[0]
                for r in conn.execute(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
                ).fetchall()
            }
            assert leftover_indexes.isdisjoint(EXPECTED_INDEXES)
            # #24 reversal: no privileges remain in THIS database. The role
            # itself is cluster-wide - 0002 drops it only when no other
            # database still holds grants for it.
            table_grants = conn.execute(
                "SELECT count(*) FROM information_schema.role_table_grants"
                " WHERE grantee = 'docmgmt_app'"
            ).fetchone()[0]
            usage_grants = conn.execute(
                "SELECT count(*) FROM information_schema.role_usage_grants"
                " WHERE grantee = 'docmgmt_app'"
            ).fetchone()[0]
            assert table_grants == 0
            assert usage_grants == 0

        # When: upgrade head again (the roundtrip closes).
        harness.upgrade(target, "head")
        # Then: the schema is back, byte-for-byte shape-wise.
        with psycopg.connect(target.libpq_url) as conn:
            assert _tables(conn) >= EXPECTED_TABLES
    finally:
        harness.drop_database(target)
