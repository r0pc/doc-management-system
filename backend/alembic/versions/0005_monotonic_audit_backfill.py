"""Close the #8 monotonicity hole and the #24 audit-visibility hole left by 0004.

Two independent defects shipped in 0004 are repaired here.

--- #8: check_monotonic() must never let an automated writer lower a label ---

0002 compared NEW against *every* prior classification of the document. That
was too wide: once a human had lowered a label, the next automated write at
the new (lower) level was rejected against the stale historical high-water
mark, so the pipeline could never re-agree with the reviewer.

0004 fixed that correctly by comparing NEW against the document's CURRENT
classification only (``documents.current_classification_id``) - that part is
preserved verbatim below. But 0004 also wrapped the rank comparison in

    IF curr_version_id = NEW.version_id THEN ... END IF;

which silently disarmed the trigger for every write naming a *different*
version. Since the classifier runs per version, an automated writer could
lower the effective label of a document simply by classifying a new version -
exactly the automated downgrade #8 forbids, and unqualified in AGENTS.md:
"Security level never decreases automatically ... Only a human reviewer lowers
a label." The guard is removed. Scope stays 'current classification'; the
comparison itself is now unconditional for ``decided_by <> 'human'``.

The RAISE message returns to 0002's wording, which the spec and
``tests/integration/test_monotonic_trigger.py::LOWER_MESSAGE`` both pin:
'automated reclassification cannot lower security level'. 0004 had shortened
it, breaking that contract.

--- #24: access_log.tenant_id backfill, and NOT NULL ---

0004 added ``access_log.tenant_id`` as NULLABLE, then put ENABLE + FORCE ROW
LEVEL SECURITY on the table with ``tenant_id = app.tenant_id`` in both USING
and WITH CHECK. It never backfilled. Every audit row written before 0004
therefore keeps ``tenant_id IS NULL``, and ``NULL = <uuid>`` is NULL, never
true - so the entire pre-upgrade audit history became permanently invisible
to ``docmgmt_app``. For an append-only audit trail (#24) that is silent
history loss on upgrade, not a cosmetic gap.

This revision:

1. Backfills from the owning document (``access_log.document_id ->
   documents.tenant_id``). access_log deliberately carries no FKs (#24), so
   this is a best-effort join, not a constraint - rows whose document has
   since been hard-deleted simply do not resolve.

2. Assigns the remaining unresolvable rows - those with ``document_id IS
   NULL``, i.e. tenant-level events such as sign-in or admin actions logged
   before 0004 - to the reserved nil UUID
   ``00000000-0000-0000-0000-000000000000``.

   Why not delete them: the audit trail is append-only at the grant layer
   (#24). A migration that erases audit rows to make a constraint fit is the
   worst available option and is not on the table.

   Why not leave them NULL: that is precisely the defect. A NULL row is
   invisible to every tenant forever, which reads as "the record does not
   exist" rather than "the record is unattributed".

   Why the nil UUID: ``access_log`` has no FK to ``tenants`` (#24), so the
   sentinel needs - and gets - no ``tenants`` row. Nothing fabricates a
   tenant, no real tenant can ever be issued the nil UUID, and no application
   session binds it (``bind_tenant`` always binds the caller's real tenant).
   The rows stay in the table and stay reachable through one documented
   forensic path - an operator binding
   ``SET LOCAL app.tenant_id = '00000000-0000-0000-0000-000000000000'`` -
   instead of being unreachable by anyone. Unattributed, but not lost.

3. Sets the column NOT NULL. The RLS WITH CHECK already rejects a NULL
   tenant_id, but it does so as an opaque "new row violates row-level
   security policy". NOT NULL turns the same mistake into a named, greppable
   not-null violation, and guarantees no future writer can recreate the
   invisible-row class this revision exists to drain.
   (PostgreSQL 16 records NOT NULL in ``pg_attribute.attnotnull``, not in
   ``pg_constraint``, so the #24 "access_log carries only its PK constraint"
   assertion in the roundtrip test still holds.)

RLS interaction: like 0003, this migration must work whether the operator is
a superuser (bypasses RLS) or merely the table owner (FORCE keeps the owner
subject to policy, so an un-bound session would see - and update - zero
rows). Rather than bind a single tenant GUC, which cannot span a cross-tenant
backfill, the two tables involved are taken out of RLS for the duration of
the backfill and put straight back. DDL is transactional in PostgreSQL and
alembic runs the revision in one transaction, so there is no window in which
a concurrent session observes the tables unprotected.

downgrade() restores 0004 exactly where 0004's state is recoverable: the
function is reinstated byte-for-byte and the NOT NULL is dropped. It reverts
only the nil-UUID sentinel to NULL - the value this revision invented. It
deliberately does NOT null the document-derived backfill: those values are
recomputable from ``documents`` (so re-upgrading is idempotent), and blanket
nulling would destroy the legitimately-tenanted ``document_id IS NULL`` rows
the application writes after 0005, which are not recomputable from anything.
"""

from __future__ import annotations

from alembic import op

revision: str = "0005_monotonic_audit_backfill"
down_revision: str | None = "0004_audit_tenant_isolation"
branch_labels: str | None = None
depends_on: str | None = None

UNATTRIBUTED_TENANT = "00000000-0000-0000-0000-000000000000"

# 0004's function, verbatim - downgrade() must put this back untouched.
CHECK_MONOTONIC_0004 = """
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

# 0005: 0004's current-classification scope, without the version-equality guard.
CHECK_MONOTONIC_0005 = """
CREATE OR REPLACE FUNCTION check_monotonic() RETURNS trigger AS $$
DECLARE
    curr_class_id uuid;
    curr_rank smallint;
    new_rank smallint;
BEGIN
    IF NEW.decided_by <> 'human' THEN
        SELECT current_classification_id INTO curr_class_id
        FROM documents WHERE id = NEW.document_id;

        IF curr_class_id IS NOT NULL THEN
            SELECT sl.rank INTO curr_rank
            FROM classifications cl
            JOIN security_levels sl ON sl.id = cl.level_id
            WHERE cl.id = curr_class_id;

            SELECT sl.rank INTO new_rank
            FROM security_levels sl WHERE sl.id = NEW.level_id;

            IF new_rank < curr_rank THEN
                RAISE EXCEPTION
                    'automated reclassification cannot lower security level';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def _suspend_rls() -> None:
    """Take access_log/documents out of RLS so the backfill is not filtered."""
    op.execute("ALTER TABLE access_log DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE documents DISABLE ROW LEVEL SECURITY")


def _restore_rls() -> None:
    """Put ENABLE + FORCE back on both tables (#26); policies were never dropped."""
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE documents FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE access_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE access_log FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    # --- #8: drop 0004's version-equality guard, keep its current-class scope ---
    op.execute(CHECK_MONOTONIC_0005)

    # --- #24: make the pre-0004 audit history visible again ---
    _suspend_rls()

    # Resolve every row we can from the owning document.
    op.execute(
        """
        UPDATE access_log AS al
        SET tenant_id = d.tenant_id
        FROM documents AS d
        WHERE al.tenant_id IS NULL
          AND al.document_id IS NOT NULL
          AND al.document_id = d.id
        """
    )

    # Park what is left under the reserved nil UUID rather than deleting it
    # or leaving it unreachable (see module docstring).
    op.execute(
        # Static SQL: the sentinel is a compile-time literal, nothing is interpolated.
        f"UPDATE access_log SET tenant_id = '{UNATTRIBUTED_TENANT}'"  # noqa: S608
        " WHERE tenant_id IS NULL"
    )

    op.execute("ALTER TABLE access_log ALTER COLUMN tenant_id SET NOT NULL")

    _restore_rls()


def downgrade() -> None:
    _suspend_rls()

    op.execute("ALTER TABLE access_log ALTER COLUMN tenant_id DROP NOT NULL")
    # Only the sentinel is this revision's invention; document-derived values
    # stay (recomputable, and nulling them would destroy post-0005 writes).
    op.execute(
        # Static SQL: the sentinel is a compile-time literal, nothing is interpolated.
        "UPDATE access_log SET tenant_id = NULL"  # noqa: S608
        f" WHERE tenant_id = '{UNATTRIBUTED_TENANT}'"
    )

    _restore_rls()

    op.execute(CHECK_MONOTONIC_0004)
