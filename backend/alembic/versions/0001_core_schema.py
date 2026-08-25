"""Core schema: all sixteen spec §6 tables plus §6.2 indexes, hand-written.

# allow: SIZE_OK - declarative 1:1 transcription of spec §6/§6.2 DDL (pure
# data tables); splitting would fragment the schema contract that
# app/db/models.py and the metadata tests treat as one unit.

Mirrors ``app/db/models.py`` column-for-column: types, nullability, defaults,
and constraint/index names follow the declarative naming convention in
``app/db/base.py`` so autogenerate diffs stay empty. Deliberate divergences
from naive DDL, each encoding an AGENTS.md invariant:

- #22  documents.current_classification_id is emitted via ALTER TABLE after
       both tables exist, DEFERRABLE INITIALLY DEFERRED (the FK pair with
       classifications.document_id is mutually circular; models.py uses
       use_alter=True for exactly this).
- #23  security_levels.rank is a separate UNIQUE column; the PK stays the
       surrogate id.
- #24  access_log.document_id / actor_id are bare uuids with no FOREIGN KEY -
       the audit trail outlives what it audits.
- #15  blobs carries no tenant and no permission columns.

Server defaults: only what models declare server-side - created_at now()
here, access_log.id as BIGSERIAL. Client-side defaults (uuid4 PKs,
processing_jobs.attempts = 0) stay client-side, matching the models.

downgrade() is the exact reverse: indexes first, then the ALTER-added FK,
then tables in reverse dependency order, then the extension.
"""

from __future__ import annotations

from alembic import op

revision: str = "0001_core_schema"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE tenants (
            id UUID NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT pk_tenants PRIMARY KEY (id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE security_levels (
            id UUID NOT NULL,
            rank SMALLINT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            CONSTRAINT pk_security_levels PRIMARY KEY (id),
            CONSTRAINT uq_security_levels_rank UNIQUE (rank),
            CONSTRAINT uq_security_levels_name UNIQUE (name)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE doc_types (
            id UUID NOT NULL,
            parent_id UUID,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            CONSTRAINT pk_doc_types PRIMARY KEY (id),
            CONSTRAINT fk_doc_types_parent_id_doc_types
                FOREIGN KEY (parent_id) REFERENCES doc_types (id),
            CONSTRAINT uq_doc_types_parent_id UNIQUE (parent_id, name)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE blobs (
            sha256 TEXT NOT NULL,
            size_bytes BIGINT NOT NULL,
            mime_sniffed TEXT NOT NULL,
            bucket_key TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT pk_blobs PRIMARY KEY (sha256)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE keywords (
            id UUID NOT NULL,
            term TEXT NOT NULL,
            idf REAL NOT NULL,
            CONSTRAINT pk_keywords PRIMARY KEY (id),
            CONSTRAINT uq_keywords_term UNIQUE (term)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE departments (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL,
            parent_id UUID,
            name TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT pk_departments PRIMARY KEY (id),
            CONSTRAINT fk_departments_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES tenants (id),
            CONSTRAINT fk_departments_parent_id_departments
                FOREIGN KEY (parent_id) REFERENCES departments (id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE users (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL,
            department_id UUID,
            oidc_sub TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL,
            clearance_rank SMALLINT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT pk_users PRIMARY KEY (id),
            CONSTRAINT uq_users_oidc_sub UNIQUE (oidc_sub),
            CONSTRAINT fk_users_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES tenants (id),
            CONSTRAINT fk_users_department_id_departments
                FOREIGN KEY (department_id) REFERENCES departments (id)
        )
        """
    )

    # current_classification_id has NO inline FK here: it is mutually circular
    # with classifications.document_id and is added below once both exist (#22).
    op.execute(
        """
        CREATE TABLE documents (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL,
            department_id UUID,
            original_filename TEXT NOT NULL,
            status TEXT NOT NULL,
            current_classification_id UUID,
            uploaded_by UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            deleted_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT pk_documents PRIMARY KEY (id),
            CONSTRAINT ck_documents_status_valid CHECK (
                status IN ('quarantined', 'processing', 'ready', 'failed', 'held')
            ),
            CONSTRAINT fk_documents_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES tenants (id),
            CONSTRAINT fk_documents_department_id_departments
                FOREIGN KEY (department_id) REFERENCES departments (id),
            CONSTRAINT fk_documents_uploaded_by_users
                FOREIGN KEY (uploaded_by) REFERENCES users (id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE document_versions (
            id UUID NOT NULL,
            document_id UUID NOT NULL,
            blob_sha256 TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            created_by UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT pk_document_versions PRIMARY KEY (id),
            CONSTRAINT uq_document_versions_document_id UNIQUE (document_id, version_no),
            CONSTRAINT fk_document_versions_document_id_documents
                FOREIGN KEY (document_id) REFERENCES documents (id),
            CONSTRAINT fk_document_versions_blob_sha256_blobs
                FOREIGN KEY (blob_sha256) REFERENCES blobs (sha256),
            CONSTRAINT fk_document_versions_created_by_users
                FOREIGN KEY (created_by) REFERENCES users (id)
        )
        """
    )

    # attempts has no server default: models.py assigns 0 client-side.
    op.execute(
        """
        CREATE TABLE processing_jobs (
            id UUID NOT NULL,
            document_id UUID NOT NULL,
            version_id UUID NOT NULL,
            stage TEXT NOT NULL,
            state TEXT NOT NULL,
            attempts INTEGER NOT NULL,
            error TEXT,
            started_at TIMESTAMP WITH TIME ZONE,
            finished_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT pk_processing_jobs PRIMARY KEY (id),
            CONSTRAINT fk_processing_jobs_document_id_documents
                FOREIGN KEY (document_id) REFERENCES documents (id),
            CONSTRAINT fk_processing_jobs_version_id_document_versions
                FOREIGN KEY (version_id) REFERENCES document_versions (id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE document_keywords (
            document_id UUID NOT NULL,
            keyword_id UUID NOT NULL,
            score REAL NOT NULL,
            CONSTRAINT pk_document_keywords PRIMARY KEY (document_id, keyword_id),
            CONSTRAINT fk_document_keywords_document_id_documents
                FOREIGN KEY (document_id) REFERENCES documents (id),
            CONSTRAINT fk_document_keywords_keyword_id_keywords
                FOREIGN KEY (keyword_id) REFERENCES keywords (id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE document_text (
            version_id UUID NOT NULL,
            tsv tsvector NOT NULL,
            embedding vector(384),
            char_count INTEGER NOT NULL,
            ocr_used BOOLEAN NOT NULL,
            CONSTRAINT pk_document_text PRIMARY KEY (version_id),
            CONSTRAINT fk_document_text_version_id_document_versions
                FOREIGN KEY (version_id) REFERENCES document_versions (id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE classifications (
            id UUID NOT NULL,
            document_id UUID NOT NULL,
            version_id UUID NOT NULL,
            level_id UUID NOT NULL,
            doc_type_id UUID,
            confidence REAL,
            decided_by TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT pk_classifications PRIMARY KEY (id),
            CONSTRAINT ck_classifications_decided_by_valid CHECK (
                decided_by IN ('rules', 'ml', 'human')
            ),
            CONSTRAINT fk_classifications_document_id_documents
                FOREIGN KEY (document_id) REFERENCES documents (id),
            CONSTRAINT fk_classifications_version_id_document_versions
                FOREIGN KEY (version_id) REFERENCES document_versions (id),
            CONSTRAINT fk_classifications_level_id_security_levels
                FOREIGN KEY (level_id) REFERENCES security_levels (id),
            CONSTRAINT fk_classifications_doc_type_id_doc_types
                FOREIGN KEY (doc_type_id) REFERENCES doc_types (id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE findings (
            id UUID NOT NULL,
            classification_id UUID NOT NULL,
            entity_type TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            page_no INTEGER,
            char_start INTEGER NOT NULL,
            char_end INTEGER NOT NULL,
            score REAL NOT NULL,
            CONSTRAINT pk_findings PRIMARY KEY (id),
            CONSTRAINT fk_findings_classification_id_classifications
                FOREIGN KEY (classification_id) REFERENCES classifications (id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE review_items (
            id UUID NOT NULL,
            document_id UUID NOT NULL,
            assigned_to UUID,
            state TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            resolved_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT pk_review_items PRIMARY KEY (id),
            CONSTRAINT fk_review_items_document_id_documents
                FOREIGN KEY (document_id) REFERENCES documents (id),
            CONSTRAINT fk_review_items_assigned_to_users
                FOREIGN KEY (assigned_to) REFERENCES users (id)
        )
        """
    )

    # Bare uuid columns, no FOREIGN KEYs: audit rows survive deletes of the
    # documents/actors they record (#24). BIGSERIAL gives the id sequence the
    # application role's INSERT grant depends on (see 0002).
    op.execute(
        """
        CREATE TABLE access_log (
            id BIGSERIAL NOT NULL,
            document_id UUID,
            actor_id UUID,
            action TEXT NOT NULL,
            ip INET,
            user_agent TEXT,
            ts TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT pk_access_log PRIMARY KEY (id)
        )
        """
    )

    # The circular half of the FK pair, deferrable so a document and its first
    # classification can be written in one transaction regardless of order (#22).
    op.execute(
        """
        ALTER TABLE documents
            ADD CONSTRAINT fk_documents_current_classification_id_classifications
            FOREIGN KEY (current_classification_id) REFERENCES classifications (id)
            DEFERRABLE INITIALLY DEFERRED
        """
    )

    # --- spec §6.2 indexes, verbatim ---
    op.execute(
        """
        CREATE INDEX ix_documents_tenant_status ON documents (tenant_id, status)
            WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_versions_doc_version
            ON document_versions (document_id, version_no DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_classifications_doc_created
            ON classifications (document_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_access_log_document_ts ON access_log (document_id, ts DESC)
        """
    )
    op.execute("CREATE INDEX ix_access_log_actor_ts ON access_log (actor_id, ts DESC)")
    op.execute(
        """
        CREATE INDEX ix_documents_tenant_department ON documents (tenant_id, department_id)
            WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_processing_jobs_document_stage
            ON processing_jobs (document_id, stage)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_processing_jobs_state_live ON processing_jobs (state)
            WHERE state IN ('queued', 'running')
        """
    )
    op.execute("CREATE INDEX ix_document_text_tsv_gin ON document_text USING gin (tsv)")
    op.execute(
        """
        CREATE INDEX ix_document_text_embedding_hnsw
            ON document_text USING hnsw (embedding vector_cosine_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_keywords_keyword_score
            ON document_keywords (keyword_id, score DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_document_keywords_keyword_score")
    op.execute("DROP INDEX ix_document_text_embedding_hnsw")
    op.execute("DROP INDEX ix_document_text_tsv_gin")
    op.execute("DROP INDEX ix_processing_jobs_state_live")
    op.execute("DROP INDEX ix_processing_jobs_document_stage")
    op.execute("DROP INDEX ix_documents_tenant_department")
    op.execute("DROP INDEX ix_access_log_actor_ts")
    op.execute("DROP INDEX ix_access_log_document_ts")
    op.execute("DROP INDEX ix_classifications_doc_created")
    op.execute("DROP INDEX ix_document_versions_doc_version")
    op.execute("DROP INDEX ix_documents_tenant_status")

    op.execute(
        "ALTER TABLE documents"
        " DROP CONSTRAINT fk_documents_current_classification_id_classifications"
    )

    op.execute("DROP TABLE access_log")
    op.execute("DROP TABLE review_items")
    op.execute("DROP TABLE findings")
    op.execute("DROP TABLE classifications")
    op.execute("DROP TABLE document_text")
    op.execute("DROP TABLE document_keywords")
    op.execute("DROP TABLE processing_jobs")
    op.execute("DROP TABLE document_versions")
    op.execute("DROP TABLE documents")
    op.execute("DROP TABLE users")
    op.execute("DROP TABLE departments")
    op.execute("DROP TABLE keywords")
    op.execute("DROP TABLE blobs")
    op.execute("DROP TABLE doc_types")
    op.execute("DROP TABLE security_levels")
    op.execute("DROP TABLE tenants")

    op.execute("DROP EXTENSION IF EXISTS vector")
