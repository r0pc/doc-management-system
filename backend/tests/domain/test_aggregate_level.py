"""Truth table for domain.policy.aggregate_level (max-wins with Internal floor).

Rank — never score — drives the level. CNIC escalates count-aware: >= 3 hits
push the contribution to Restricted, otherwise a single hit is Confidential.
"""

import pytest

from app.domain.models import DEFAULT_FLOOR_RANK, LEVEL_RANK, Finding, LevelName
from app.domain.policy import aggregate_level
from app.domain.taxonomy import Taxonomy

CARD = "card_number"
CNIC = "cnic"
SALARY_PERSON = "salary_with_named_person"
EMAIL_DOMAIN = "internal_email_domain"
NAMED_EMPLOYEE = "named_employee"


def finding(entity_type: str, score: float = 0.95, page_no: int | None = 1) -> Finding:
    return Finding(
        entity_type=entity_type,
        rule_id=f"rule-{entity_type}",
        page_no=page_no,
        char_start=0,
        char_end=8,
        score=score,
    )


@pytest.mark.parametrize(
    ("entity_types", "expected_rank"),
    [
        ([], DEFAULT_FLOOR_RANK),  # absence of evidence defaults UP to Internal
        ([CNIC], 3),  # single CNIC -> Confidential
        ([CNIC, CNIC], 3),  # below threshold stays Confidential
        ([CNIC, CNIC, CNIC], 4),  # threshold reached -> Restricted
        ([CNIC, CNIC, CNIC, CNIC], 4),  # capped at Restricted
        ([CARD], 4),
        ([SALARY_PERSON], 4),
        ([EMAIL_DOMAIN], 3),
        ([NAMED_EMPLOYEE], 2),
        # Max-wins across mixed findings.
        ([NAMED_EMPLOYEE, CARD], 4),
        ([NAMED_EMPLOYEE, EMAIL_DOMAIN], 3),
        ([EMAIL_DOMAIN, CNIC, CNIC, CNIC], 4),
        ([NAMED_EMPLOYEE, NAMED_EMPLOYEE], 2),
    ],
)
def test_aggregate_truth_table(entity_types: list[str], expected_rank: int) -> None:
    findings = [finding(entity) for entity in entity_types]
    assert aggregate_level(findings, Taxonomy.default()) == expected_rank


@pytest.mark.parametrize("score", [0.0, 0.5, 0.99])
def test_score_never_drives_the_rank(score: float) -> None:
    assert aggregate_level([finding(CARD, score=score)], Taxonomy.default()) == 4


def test_page_no_none_is_tolerated() -> None:
    assert aggregate_level([finding(CNIC, page_no=None)], Taxonomy.default()) == 3


def test_floor_equals_internal_rank_constant() -> None:
    assert DEFAULT_FLOOR_RANK == LEVEL_RANK[LevelName.INTERNAL] == 2


@pytest.mark.parametrize("unknown", ["passport_no", "iban"])
def test_unknown_entity_type_fails_loud(unknown: str) -> None:
    with pytest.raises(ValueError, match="unknown entity_type"):
        aggregate_level([finding(unknown)], Taxonomy.default())
    with pytest.raises(ValueError, match="unknown entity_type"):
        Taxonomy.default().rank_for(finding(unknown))


def test_custom_taxonomy_rank_map_is_honoured() -> None:
    tax = Taxonomy(entity_rank={NAMED_EMPLOYEE: 2})
    assert aggregate_level([finding(NAMED_EMPLOYEE)], tax) == 2
