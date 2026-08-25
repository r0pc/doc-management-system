"""Finding synthesis and summary helpers for the classification pipeline.

This module deliberately does NOT reimplement level aggregation: max-wins and
the Internal floor (#9) live in domain.policy.aggregate_level, and the DB
check_monotonic trigger stays the monotonicity authority (#8). What lives here
is the thin construction of Findings — character offsets, never matched text
(#12) — and their summarisation.
"""

from collections.abc import Sequence
from typing import Final

from app.domain.models import Finding
from app.domain.policy import aggregate_level
from app.domain.taxonomy import Taxonomy

_SUMMARY_COUNTS: Final[str] = "counts"
_SUMMARY_RANK: Final[str] = "implied_level_rank"


def build_finding(
    entity_type: str,
    rule_id: str,
    page_no: int | None,
    char_start: int,
    char_end: int,
    score: float,
) -> Finding:
    """Thin Finding ctor enforcing offsets-not-text (#12).

    Offsets must be real integers with 0 <= start <= end; anything else (e.g. a
    matched-text string smuggled into an offset slot) fails loud here rather
    than leaking sensitive values into secondary storage.
    """
    for name, offset in (("char_start", char_start), ("char_end", char_end)):
        if not isinstance(offset, int):
            raise ValueError(f"{name} must be an int character offset, got {type(offset).__name__}")
    if char_start < 0 or char_end < char_start:
        raise ValueError(f"invalid character offsets [{char_start}, {char_end})")
    return Finding(
        entity_type=entity_type,
        rule_id=rule_id,
        page_no=page_no,
        char_start=char_start,
        char_end=char_end,
        score=score,
    )


def summarize_findings(
    findings: Sequence[Finding], tax: Taxonomy | None = None
) -> dict[str, object]:
    """Counts by entity_type plus the implied security-level rank.

    The rank comes straight from domain.policy.aggregate_level (max-wins, CNIC
    count-aware escalation, Internal floor #9); unknown entity types fail loud
    via Taxonomy.rank_for rather than silently mapping to the floor.
    """
    taxonomy = tax if tax is not None else Taxonomy.default()
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.entity_type] = counts.get(finding.entity_type, 0) + 1
    return {
        _SUMMARY_COUNTS: dict(sorted(counts.items())),
        _SUMMARY_RANK: aggregate_level(findings, taxonomy),
    }
