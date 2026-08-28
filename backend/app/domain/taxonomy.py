"""Document-type taxonomy as data: entity type -> security rank.

Encodes the spec §3.2 policy table. Pure and deterministic — no I/O, no clock,
no randomness — so both the API and the classification workers aggregate
labels identically.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.domain.models import Finding

# CNIC is count-aware: a single hit is Confidential, but >= CNIC_RESTRICTED_COUNT
# hits escalate to Restricted. The escalation itself lives in policy.aggregate_level;
# these constants are the shared contract between the two modules.
CNIC_ENTITY_TYPE: Final[str] = "cnic"
CNIC_RESTRICTED_COUNT: Final[int] = 3

# Base per-finding ranks from spec §3.2. CNIC's base rank is Confidential; the
# count-aware escalation to Restricted is applied by aggregate_level.
_SPEC_ENTITY_RANKS: Final[Mapping[str, int]] = {
    "card_number": 4,
    CNIC_ENTITY_TYPE: 3,
    "bank_account": 4,
    "passport_number": 4,
    "salary_with_named_person": 4,
    "internal_email_domain": 3,
    "named_employee": 2,
}


@dataclass(frozen=True)
class Taxonomy:
    """Immutable entity_type -> rank map used for label aggregation."""

    entity_rank: Mapping[str, int]

    @classmethod
    def default(cls) -> Taxonomy:
        return cls(entity_rank=dict(_SPEC_ENTITY_RANKS))

    def rank_for(self, finding: Finding) -> int:
        """Rank contributed by a single finding; unknown types fail loud."""
        try:
            return self.entity_rank[finding.entity_type]
        except KeyError:
            raise ValueError(f"unknown entity_type: {finding.entity_type!r}") from None
