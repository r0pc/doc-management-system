"""Pure authorisation and label-aggregation policy.

The single source of truth both the API and the workers import for every
authorisation decision and security-level aggregation. Functions here are
pure: no session, no request object, no I/O — so the suite runs as a
parametrised table with no fixtures.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.models import (
    DEFAULT_FLOOR_RANK,
    LEVEL_RANK,
    Action,
    DocumentRef,
    Finding,
    LevelName,
    UserCtx,
)
from app.domain.taxonomy import CNIC_ENTITY_TYPE, CNIC_RESTRICTED_COUNT, Taxonomy


def can_access(user: UserCtx, doc: DocumentRef, action: Action) -> bool:
    """Two-axis access decision (invariant #25): clearance rank x department.

    Check order is part of the contract: tenant, deletion, level, department.
    Every action is gated identically this phase; per-action permissions arrive
    with the permission matrix wave. The object key plays no part here — it is
    never an authorisation boundary (#15).
    """
    # Axis 0: tenancy. A foreign-tenant document must be indistinguishable from
    # a nonexistent one downstream (#31); here a mismatch is simply a denial.
    if user.tenant_id != doc.tenant_id:
        return False
    # Soft-deleted documents are invisible to every action this phase; the
    # restore flow will re-introduce access explicitly.
    if doc.deleted_at is not None:
        return False
    # Axis 1 ("how sensitive"): caller's clearance must meet the document level.
    if user.clearance_rank < doc.level_rank:
        return False
    # Axis 2 ("whose business"): department-scoped docs require visibility;
    # docs belonging to no department are tenant-wide. A document shared with
    # several departments is visible to each of them — ANY match admits, which
    # is what makes sharing possible without moving ownership.
    if not doc.department_ids:
        return True
    return any(dept in user.visible_department_ids for dept in doc.department_ids)


def aggregate_level(findings: Sequence[Finding], tax: Taxonomy) -> int:
    """Max-wins aggregation of finding ranks into a security-level rank.

    Application-side half of invariant #8 — the DB ``check_monotonic`` trigger
    remains the authority; this function only ever proposes. The result never
    falls below DEFAULT_FLOOR_RANK (#9): an empty finding set aggregates to
    Internal, never Public. Unknown entity types fail loud via
    ``Taxonomy.rank_for`` rather than silently mapping to the floor.

    CNIC is count-aware: >= CNIC_RESTRICTED_COUNT hits contribute Restricted,
    regardless of each hit's base rank. Score never drives the level — rank does.
    """
    ranks = [tax.rank_for(finding) for finding in findings]
    cnic_hits = sum(1 for finding in findings if finding.entity_type == CNIC_ENTITY_TYPE)
    if cnic_hits >= CNIC_RESTRICTED_COUNT:
        ranks.append(LEVEL_RANK[LevelName.RESTRICTED])
    return max(ranks, default=DEFAULT_FLOOR_RANK)
