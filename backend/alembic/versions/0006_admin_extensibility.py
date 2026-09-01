"""0006 admin extensibility: tenant doc types, prototypes, detector rules (#26, #10).

doc_types was outside RLS; its new policy admits tenant_id IS NULL so the
seeded global types stay visible to every tenant. detector_rules makes
validator_kind NOT NULL at the schema level, so a bare regex cannot be
stored at all (#10).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_admin_extensibility"
down_revision: str | None = "d7d1c3d1c60b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add nullable tenant_id column to doc_types
    op.execute(
        """
        ALTER TABLE doc_types
        ADD COLUMN tenant_id UUID NULL REFERENCES tenants(id) ON DELETE CASCADE;
        """
    )

    # 2. Enable + force RLS on doc_types admitting global types (tenant_id IS NULL)
    op.execute("ALTER TABLE doc_types ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE doc_types FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON doc_types FOR ALL TO docmgmt_app
            USING (
                tenant_id IS NULL
                OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )

    # 3. Create doc_type_prototypes table + HNSW vector index + RLS
    op.execute(
        """
        CREATE TABLE doc_type_prototypes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            doc_type_id UUID NOT NULL REFERENCES doc_types(id) ON DELETE CASCADE,
            centroid_vector vector(384) NOT NULL,
            sample_count INT NOT NULL CHECK (sample_count >= 5),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_doc_type_prototypes_tenant_doctype UNIQUE (tenant_id, doc_type_id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX idx_doc_type_prototypes_hnsw
            ON doc_type_prototypes USING hnsw (centroid_vector vector_cosine_ops);
        """
    )
    op.execute("ALTER TABLE doc_type_prototypes ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE doc_type_prototypes FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON doc_type_prototypes
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )

    # 4. Create detector_rules table + RLS
    op.execute(
        """
        CREATE TABLE detector_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            entity_type TEXT NOT NULL,
            pattern TEXT NOT NULL,
            validator_kind TEXT NOT NULL,
            validator_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            context_words TEXT[] NOT NULL,
            level_rank INT NOT NULL CHECK (level_rank BETWEEN 1 AND 4),
            enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_detector_rules_tenant_entity UNIQUE (tenant_id, entity_type),
            CONSTRAINT chk_detector_rules_context_words CHECK (cardinality(context_words) > 0)
        );
        """
    )
    op.execute("ALTER TABLE detector_rules ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE detector_rules FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON detector_rules
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )

    # 5. Grant permissions on new tables to docmgmt_app
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE
        ON TABLE doc_type_prototypes, detector_rules TO docmgmt_app;
        """
    )


def downgrade() -> None:
    op.execute("REVOKE ALL ON TABLE doc_type_prototypes, detector_rules FROM docmgmt_app;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON detector_rules;")
    op.execute("DROP TABLE IF EXISTS detector_rules;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON doc_type_prototypes;")
    op.execute("DROP TABLE IF EXISTS doc_type_prototypes;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON doc_types;")
    op.execute("ALTER TABLE doc_types NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE doc_types DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE doc_types DROP COLUMN IF EXISTS tenant_id;")
