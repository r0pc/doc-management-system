"""Security hardening: monotonic trigger, app role grants, row-level security.

Three controls, each an AGENTS.md invariant enforced in the database - not in
application code that a future refactor could silently drop:

- #8  check_monotonic(): an automated decision (decided_by <> 'human') may
      propose a type or RAISE a level but can never LOWER one. Only a human
      reclassification lowers a label. The application-side aggregate_level
      only proposes; this trigger is the authority.
- #24 docmgmt_app gets DML on the working tables but INSERT/SELECT only on
      access_log: the audit trail is append-only at the grant layer (the
      table also has no UPDATE-prone FKs and its id sequence is granted for
      the bigserial INSERT path).
- #26 RLS with ENABLE + FORCE on every tenanted table; policies read
      app.tenant_id via NULLIF(current_setting(..., true), '')::uuid. The
      NULLIF matters: once a session has bound the GUC even once, PostgreSQL
      keeps an empty-string placeholder after the transaction-local value
      expires, so a bare current_setting would return '' and ''::uuid would
      ERROR on pooled connections. With NULLIF, both never-set (NULL) and
      expired ('') resolve to NULL, and NULL = tenant_id filters every row:
      an unbound session sees zero rows - fail-closed. FORCE keeps even
      non-superuser table owners subject to policy.

Child tables carry no tenant_id column of their own, so their policies
resolve the tenant through documents (findings through classifications ->
documents). blobs is deliberately excluded: it carries no tenant by design
(#15); keywords/document_text/security_levels/doc_types/access_log are
global/shared and stay outside RLS.

Note on the spec's literal SQL: the spec's correlation aliases ``old``/``new``
collide with PL/pgSQL's implicit NEW/OLD trigger variables, so the function
uses ``prior``/``prior_level``/``candidate`` instead - semantics identical,
shadowing impossible.
"""

from __future__ import annotations

from alembic import op

revision: str = "0002_security_hardening"
down_revision: str | None = "0001_core_schema"
branch_labels: str | None = None
depends_on: str | None = None

_TENANTED_TABLES = (
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
)

_WORKING_TABLES_GRANT = (
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
    "tenants, departments, users, blobs, documents, document_versions,"
    " security_levels, doc_types, processing_jobs, keywords, document_keywords,"
    " document_text, classifications, findings, review_items TO docmgmt_app"
)
_WORKING_TABLES_REVOKE = (
    "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE "
    "tenants, departments, users, blobs, documents, document_versions,"
    " security_levels, doc_types, processing_jobs, keywords, document_keywords,"
    " document_text, classifications, findings, review_items FROM docmgmt_app"
)


def upgrade() -> None:
    # --- #8: automated reclassification can never lower the security level ---
    op.execute(
        """
        CREATE FUNCTION check_monotonic() RETURNS trigger AS $$
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

    # --- #24: least-privilege application role ---
    # Dev-only password mirroring the compose POSTGRES_PASSWORD default; any
    # real deployment provisions this role from a secret store instead.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docmgmt_app') THEN
                CREATE ROLE docmgmt_app LOGIN PASSWORD 'docmgmt';
            END IF;
        END
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO docmgmt_app")
    op.execute(_WORKING_TABLES_GRANT)
    op.execute("GRANT INSERT, SELECT ON TABLE access_log TO docmgmt_app")
    # Belt and braces: even if a future blanket grant re-adds them, spell out
    # that history is not editable through the application role (#24).
    op.execute("REVOKE UPDATE, DELETE ON TABLE access_log FROM docmgmt_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE access_log_id_seq TO docmgmt_app")

    # --- #26: tenant isolation lives in RLS, not remembered WHERE clauses ---
    # tenants IS the tenant row: match on id.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenants
            USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )

    for direct in ("departments", "users", "documents"):
        op.execute(f"ALTER TABLE {direct} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {direct} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {direct}
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )

    for child in (
        "document_versions",
        "processing_jobs",
        "document_keywords",
        "review_items",
        "classifications",
    ):
        op.execute(f"ALTER TABLE {child} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {child} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {child}
                USING (EXISTS (
                    SELECT 1 FROM documents d
                    WHERE d.id = {child}.document_id
                      AND d.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                ))
                WITH CHECK (EXISTS (
                    SELECT 1 FROM documents d
                    WHERE d.id = {child}.document_id
                      AND d.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                ))
            """  # noqa: S608 - {child} comes from the fixed literal tuple above
        )

    # findings reaches its tenant two hops away: classification -> document.
    op.execute("ALTER TABLE findings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE findings FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON findings
            USING (EXISTS (
                SELECT 1
                FROM classifications cl JOIN documents d ON d.id = cl.document_id
                WHERE cl.id = findings.classification_id
                  AND d.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            ))
            WITH CHECK (EXISTS (
                SELECT 1
                FROM classifications cl JOIN documents d ON d.id = cl.document_id
                WHERE cl.id = findings.classification_id
                  AND d.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            ))
        """
    )


def downgrade() -> None:
    for table in _TENANTED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute(_WORKING_TABLES_REVOKE)
    op.execute("REVOKE INSERT, SELECT ON TABLE access_log FROM docmgmt_app")
    op.execute("REVOKE USAGE, SELECT ON SEQUENCE access_log_id_seq FROM docmgmt_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM docmgmt_app")
    # Roles are cluster-wide: if this database is not the only one holding
    # grants for the role, the drop must not fail the whole downgrade. All
    # privileges IN THIS database are revoked above; only then attempt the
    # drop and defer to other databases' cleanups otherwise.
    op.execute(
        """
        DO $$
        BEGIN
            DROP ROLE IF EXISTS docmgmt_app;
        EXCEPTION
            WHEN dependent_objects_still_exist THEN
                RAISE NOTICE
                    'role docmgmt_app still has privileges in other databases;'
                    ' left in place';
        END
        $$
        """
    )

    op.execute("DROP TRIGGER IF EXISTS trg_check_monotonic ON classifications")
    op.execute("DROP FUNCTION IF EXISTS check_monotonic()")
