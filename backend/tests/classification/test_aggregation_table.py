"""Aggregation wiring table: finding synthesis -> domain policy aggregation.

aggregate.py owns FINDING SYNTHESIS and summaries only; the max-wins policy
table and the Internal floor (#9) live in domain.policy — these tests prove the
wiring by driving domain.aggregate_level through synthesized Findings.
"""

import pytest

from app.classification.aggregate import build_finding, summarize_findings
from app.domain.models import Finding
from app.domain.policy import aggregate_level
from app.domain.taxonomy import Taxonomy

CNIC = "cnic"
CARD = "card_number"
NAMED_EMPLOYEE = "named_employee"


def test_build_finding_produces_offset_only_finding() -> None:
    finding = build_finding(
        entity_type=CNIC,
        rule_id="cnic-shape",
        page_no=2,
        char_start=10,
        char_end=25,
        score=0.9,
    )
    assert isinstance(finding, Finding)
    assert finding == Finding(
        entity_type=CNIC,
        rule_id="cnic-shape",
        page_no=2,
        char_start=10,
        char_end=25,
        score=0.9,
    )


@pytest.mark.parametrize(
    ("char_start", "char_end"),
    [(-1, 5), (7, 7 - 1), (-3, -1)],
)
def test_build_finding_rejects_bad_offsets(char_start: int, char_end: int) -> None:
    with pytest.raises(ValueError, match="offset"):
        build_finding(CNIC, "rule", 1, char_start, char_end, 0.9)


def test_build_finding_rejects_text_smuggled_as_offsets() -> None:
    # Invariant #12: findings carry character offsets, never matched text.
    with pytest.raises(ValueError, match="offset"):
        build_finding(CNIC, "rule", 1, "42101-1234567-8", 25, 0.9)  # type: ignore[arg-type]


def test_empty_findings_summarize_to_internal_floor() -> None:
    summary = summarize_findings([])
    assert summary["counts"] == {}
    assert summary["implied_level_rank"] == 2


def test_three_cnics_summarize_to_restricted() -> None:
    findings = [build_finding(CNIC, f"rule-{i}", 1, i, i + 15, 0.9) for i in range(3)]
    summary = summarize_findings(findings)
    assert summary["counts"] == {CNIC: 3}
    assert summary["implied_level_rank"] == 4


def test_single_cnic_summarizes_to_confidential() -> None:
    summary = summarize_findings([build_finding(CNIC, "rule", None, 0, 15, 0.8)])
    assert summary["implied_level_rank"] == 3


def test_mixed_findings_take_the_max_rank() -> None:
    findings = [
        build_finding(NAMED_EMPLOYEE, "rule-a", 1, 0, 5, 0.7),
        build_finding(CARD, "rule-b", 1, 20, 36, 0.95),
    ]
    summary = summarize_findings(findings)
    assert summary["counts"] == {NAMED_EMPLOYEE: 1, CARD: 1}
    assert summary["implied_level_rank"] == 4


def test_summary_implied_rank_matches_domain_policy_directly() -> None:
    findings = [
        build_finding(NAMED_EMPLOYEE, "rule-a", 1, 0, 5, 0.7),
        build_finding(CNIC, "rule-b", 1, 20, 35, 0.9),
    ]
    tax = Taxonomy.default()
    summary = summarize_findings(findings, tax)
    assert summary["implied_level_rank"] == aggregate_level(findings, tax)


def test_unknown_entity_type_fails_loud_through_domain() -> None:
    with pytest.raises(ValueError, match="unknown entity_type"):
        summarize_findings([build_finding("klingon_clearance", "rule", 1, 0, 5, 0.9)])
