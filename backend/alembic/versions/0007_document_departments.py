"""Documents belong to a SET of departments, not one.

Every document took its department from whoever uploaded it
(``uploads.py``: ``department_id=user.department_id``). With the demo corpus
uploaded by an HQ admin, all 62 documents were HQ-owned — and because the
visibility subtree walks *downward*, HR and Engineering are children of HQ and
so could not see any of them. Three of the five demo accounts opened to an
empty repository, which reads as a broken app rather than as the department
axis working.

``document_departments`` makes membership a set: a document is visible if ANY
of its departments is in the caller's subtree. ``documents.department_id`` is
kept as the OWNING department (who uploaded it, shown in the UI) and is no
longer consulted for access — one table decides visibility, so the two cannot
drift into disagreeing about who may read what.

Backfill gives every existing document its current owning department plus the
tenant root, which is what makes the corpus visible to HQ while leaving room
for it to be narrowed afterwards.

Revision ID: 0007_document_departments
Revises: 0006_admin_extensibility
"""

from __future__ import annotations

from alembic import op

revision: str = "0007_document_departments"
down_revision: str | None = "0006_admin_extensibility"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_departments (
            document_id UUID NOT NULL,
            department_id UUID NOT NULL,
            tenant_id UUID NOT NULL,
            CONSTRAINT pk_document_departments PRIMARY KEY (document_id, department_id),
            CONSTRAINT fk_document_departments_document_id_documents
                FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
            CONSTRAINT fk_document_departments_department_id_departments
                FOREIGN KEY (department_id) REFERENCES departments (id),
            CONSTRAINT fk_document_departments_tenant_id_tenants
                FOREIGN KEY (tenant_id) REFERENCES tenants (id)
        )
        """
    )
    # The visibility predicate looks up by department, so that is the lookup
    # this index has to serve; the PK already covers document_id.
    op.execute(
        "CREATE INDEX ix_document_departments_department "
        "ON document_departments (department_id, document_id)"
    )

    # --- backfill, before RLS is enabled on the new table ---
    #
    # `documents` and `departments` both FORCE row-level security, which applies
    # to the migration role too, and `app.tenant_id` cannot name every tenant at
    # once. Lift FORCE for the copy and restore it immediately after; the
    # policies themselves are never dropped.
    op.execute("ALTER TABLE documents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE departments NO FORCE ROW LEVEL SECURITY")
    try:
        # 1. The department the document already had.
        op.execute(
            """
            INSERT INTO document_departments (document_id, department_id, tenant_id)
            SELECT d.id, d.department_id, d.tenant_id
            FROM documents d
            WHERE d.department_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
        # 2. The tenant root, so the top of the org retains sight of everything
        #    that existed before this rule was enforceable.
        op.execute(
            """
            INSERT INTO document_departments (document_id, department_id, tenant_id)
            SELECT d.id, root.id, d.tenant_id
            FROM documents d
            JOIN departments root
              ON root.tenant_id = d.tenant_id AND root.parent_id IS NULL
            ON CONFLICT DO NOTHING
            """
        )
    finally:
        op.execute("ALTER TABLE documents FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE departments FORCE ROW LEVEL SECURITY")

    op.execute("ALTER TABLE document_departments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_departments FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON document_departments
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    # DELETE is required: re-assigning a document's departments removes rows.
    # This is membership, not an audit trail — #24's no-delete rule is about
    # access_log and does not apply here.
    op.execute("GRANT SELECT, INSERT, DELETE ON TABLE document_departments TO docmgmt_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON document_departments")
    op.execute("DROP TABLE IF EXISTS document_departments")
