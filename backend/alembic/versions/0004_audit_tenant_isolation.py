"""Audit tenant isolation and check_monotonic fix.

Revision ID: 0004_audit_tenant_isolation
Revises: 0003_seed_taxonomy
Create Date: 2026-08-27 12:00:00.000000

"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0004_audit_tenant_isolation"
down_revision = "0003_seed_taxonomy"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # CS-3/C-2: Add tenant_id to access_log
    op.add_column("access_log", sa.Column("tenant_id", UUID(as_uuid=True), nullable=True))
    op.execute("ALTER TABLE access_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE access_log FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON access_log
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute("GRANT SELECT ON TABLE access_log TO docmgmt_app")

    # Make document_versions.blob_sha256 nullable for H-1
    op.execute("ALTER TABLE document_versions ALTER COLUMN blob_sha256 DROP NOT NULL")

    # H-2: Fix check_monotonic trigger
    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_monotonic() RETURNS trigger AS $$
        DECLARE
            curr_class_id uuid;
            curr_rank smallint;
            new_rank smallint;
            curr_version_id uuid;
        BEGIN
            IF NEW.decided_by <> 'human' THEN
                SELECT current_classification_id INTO curr_class_id
                FROM documents WHERE id = NEW.document_id;

                IF curr_class_id IS NOT NULL THEN
                    SELECT cl.version_id, sl.rank
                    INTO curr_version_id, curr_rank
                    FROM classifications cl
                    JOIN security_levels sl ON cl.level_id = sl.id
                    WHERE cl.id = curr_class_id;

                    IF curr_version_id = NEW.version_id THEN
                        SELECT rank INTO new_rank FROM security_levels WHERE id = NEW.level_id;
                        IF new_rank < curr_rank THEN
                            RAISE EXCEPTION 'automated reclass cannot lower level';
                        END IF;
                    END IF;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_check_monotonic ON classifications")
    op.execute(
        """
        CREATE TRIGGER trg_check_monotonic
            BEFORE INSERT ON classifications
            FOR EACH ROW EXECUTE FUNCTION check_monotonic()
        """
    )

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_check_monotonic ON classifications")
    op.execute("DROP FUNCTION IF EXISTS check_monotonic()")

    # Restore old trigger (copy from 0002)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_monotonic() RETURNS trigger AS $$
        BEGIN
            IF NEW.decided_by <> 'human'
               AND EXISTS (
                   SELECT 1
                   FROM classifications prior
                        JOIN security_levels prior_level
                            ON prior_level.id = prior.level_id
                        JOIN security_levels candidate
                            ON candidate.id = NEW.level_id
                   WHERE prior.document_id = NEW.document_id
                     AND candidate.rank < prior_level.rank
               )
            THEN
                RAISE EXCEPTION
                    'automated reclassification cannot lower security level';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_check_monotonic
            BEFORE INSERT ON classifications
            FOR EACH ROW EXECUTE FUNCTION check_monotonic()
        """
    )

    op.execute("ALTER TABLE document_versions ALTER COLUMN blob_sha256 SET NOT NULL")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON access_log")
    op.execute("ALTER TABLE access_log NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE access_log DISABLE ROW LEVEL SECURITY")
    op.drop_column("access_log", "tenant_id")
