"""Schema metadata proofs: table/column/index/FK shapes without any engine.

Mirrors spec §6 (tables) and §6.2 (indexes). Encodes AGENTS.md invariants:
#12 findings store offsets, never matched text; #15 blobs carry no tenant or
permission columns; #21 classifications reference version_id; #22 the circular
documents/classifications FK is DEFERRABLE INITIALLY DEFERRED; #23 rank is a
separate unique column, never the PK; #24 access_log FKs never cascade.
"""

import uuid

import pytest
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Index,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.base import Base
from app.db.models import TSVector
from app.db.session import bind_tenant

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


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def _index(table_name: str, index_name: str) -> Index:
    by_name = {idx.name: idx for idx in _table(table_name).indexes}
    assert index_name in by_name, f"{index_name} missing on {table_name}: {sorted(by_name)}"
    return by_name[index_name]


def _check_constraint(table_name: str, fragment: str) -> CheckConstraint:
    checks = [
        c
        for c in _table(table_name).constraints
        if isinstance(c, CheckConstraint) and fragment in str(c.sqltext)
    ]
    assert len(checks) == 1, f"expected one {fragment!r} CHECK on {table_name}, got {checks}"
    return checks[0]


def test_metadata_declares_exactly_the_sixteen_spec_tables() -> None:
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_documents_current_classification_fk_is_deferrable_initially_deferred() -> None:
    fk = next(iter(_table("documents").c.current_classification_id.foreign_keys))
    assert fk.deferrable is True
    assert fk.initially == "DEFERRED"
    assert fk.use_alter is True  # DDL emitted after both tables exist


def test_classifications_reference_version_not_just_document() -> None:
    fk_targets = {fk.target_fullname for fk in _table("classifications").c.version_id.foreign_keys}
    assert fk_targets == {"document_versions.id"}


def test_security_levels_rank_is_unique_column_and_pk_is_surrogate_id() -> None:
    levels = _table("security_levels")
    assert levels.c.rank.unique is True
    assert set(levels.primary_key.columns.keys()) == {"id"}


def test_access_log_document_and_actor_are_bare_uuids_without_fk() -> None:
    log = _table("access_log")
    assert list(log.c.document_id.foreign_keys) == []
    assert list(log.c.actor_id.foreign_keys) == []


def test_access_log_pk_is_bigserial_style_biginteger() -> None:
    id_col = _table("access_log").c.id
    assert isinstance(id_col.type, BigInteger)
    assert id_col.primary_key and id_col.autoincrement


def test_blobs_carry_no_tenant_or_permission_columns() -> None:
    # Exact column set is the strongest proof of invariant #15.
    assert set(_table("blobs").columns.keys()) == {
        "sha256",
        "size_bytes",
        "mime_sniffed",
        "bucket_key",
        "created_at",
    }


def test_documents_status_check_enumerates_all_five_states() -> None:
    check = _check_constraint("documents", "status IN")
    for state in ("quarantined", "processing", "ready", "failed", "held"):
        assert state in str(check.sqltext)


def test_classifications_decided_by_check_constrains_values() -> None:
    check = _check_constraint("classifications", "decided_by IN")
    for value in ("rules", "ml", "human"):
        assert value in str(check.sqltext)


def test_partial_indexes_carry_postgresql_where() -> None:
    partials = [
        ("documents", "ix_documents_tenant_status"),
        ("documents", "ix_documents_tenant_department"),
        ("processing_jobs", "ix_processing_jobs_state_live"),
    ]
    for table_name, index_name in partials:
        idx = _index(table_name, index_name)
        where = idx.dialect_options["postgresql"]["where"]
        assert where is not None, f"{index_name} must be a partial index"


def test_document_text_has_gin_and_hnsw_indexes() -> None:
    gin = _index("document_text", "ix_document_text_tsv_gin")
    hnsw = _index("document_text", "ix_document_text_embedding_hnsw")
    assert gin.dialect_options["postgresql"]["using"] == "gin"
    assert hnsw.dialect_options["postgresql"]["using"] == "hnsw"
    assert hnsw.dialect_options["postgresql"]["ops"] == {"embedding": "vector_cosine_ops"}


def test_descending_indexes_match_spec_6_2() -> None:
    descending = [
        ("document_versions", "ix_document_versions_doc_version"),
        ("classifications", "ix_classifications_doc_created"),
        ("access_log", "ix_access_log_document_ts"),
        ("access_log", "ix_access_log_actor_ts"),
        ("document_keywords", "ix_document_keywords_keyword_score"),
    ]
    for table_name, index_name in descending:
        idx = _index(table_name, index_name)
        assert any("DESC" in str(expr).upper() for expr in idx.expressions), (
            f"{index_name} must order its last column DESC"
        )


def test_document_versions_unique_constraint_on_document_and_version_no() -> None:
    uniques = [
        c for c in _table("document_versions").constraints if isinstance(c, UniqueConstraint)
    ]
    assert any(set(u.columns.keys()) == {"document_id", "version_no"} for u in uniques), (
        f"no (document_id, version_no) UNIQUE among {uniques}"
    )


def test_document_text_tsv_and_nullable_vector_384() -> None:
    text_table = _table("document_text")
    assert isinstance(text_table.c.tsv.type, TSVector)
    assert text_table.c.tsv.type.get_col_spec() == "tsvector"
    embedding = text_table.c.embedding
    assert embedding.nullable is True
    assert embedding.type.dim == 384


def test_findings_store_offsets_never_matched_text() -> None:
    # Invariant #12: character offsets only - no column may carry matched content.
    assert set(_table("findings").columns.keys()) == {
        "id",
        "classification_id",
        "entity_type",
        "rule_id",
        "page_no",
        "char_start",
        "char_end",
        "score",
    }


def test_users_oidc_sub_unique_with_smallint_clearance_rank() -> None:
    users = _table("users")
    assert users.c.oidc_sub.unique is True
    assert users.c.clearance_rank.type.python_type is int
    assert users.c.clearance_rank.type.compile(dialect=postgresql.dialect()) == "SMALLINT"


@pytest.mark.parametrize("table_name", sorted(EXPECTED_TABLES))
def test_every_table_compiles_to_postgresql_ddl(table_name: str) -> None:
    ddl = str(CreateTable(_table(table_name)).compile(dialect=postgresql.dialect()))
    assert f"CREATE TABLE {table_name}" in ddl


def test_deferred_fk_is_emitted_via_alter_not_inline() -> None:
    # use_alter: the circular FK must not appear inside CREATE TABLE documents.
    documents_ddl = str(CreateTable(_table("documents")).compile(dialect=postgresql.dialect()))
    assert "current_classification_id" in documents_ddl
    assert "REFERENCES classifications" not in documents_ddl


def test_every_index_compiles_to_postgresql_ddl() -> None:
    index_count = 0
    for table in Base.metadata.tables.values():
        for idx in table.indexes:
            ddl = str(CreateIndex(idx).compile(dialect=postgresql.dialect()))
            assert "CREATE" in ddl
            index_count += 1
    assert index_count == 11  # spec §6.2: eleven indexes, verbatim


@pytest.mark.anyio
async def test_bind_tenant_executes_transaction_scoped_set_config() -> None:
    captured: list[tuple[str, object]] = []

    class FakeSession:
        async def execute(self, statement: object, params: object = None) -> None:
            captured.append((str(statement), params))

    tenant_id = uuid.uuid4()
    await bind_tenant(FakeSession(), tenant_id)

    sql, params = captured[0]
    assert "set_config('app.tenant_id'" in sql
    assert ":tid" in sql
    assert params == {"tid": str(tenant_id)}
