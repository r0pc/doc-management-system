# backend/tests/domain/test_tenant_taxonomy.py
"""A custom detector must not crash level aggregation."""

from __future__ import annotations

import pytest

from app.domain.models import Finding
from app.domain.policy import aggregate_level
from app.domain.taxonomy import Taxonomy


def _finding(entity_type: str) -> Finding:
    return Finding(
        entity_type=entity_type,
        rule_id="r",
        page_no=1,
        char_start=0,
        char_end=4,
        score=0.9,
    )


def test_custom_entity_type_aggregates_instead_of_raising() -> None:
    tax = Taxonomy.for_tenant({"company_api_key": 4})
    assert aggregate_level([_finding("company_api_key")], tax) == 4


def test_builtin_entity_types_are_still_present_for_a_tenant() -> None:
    tax = Taxonomy.for_tenant({"company_api_key": 4})
    assert aggregate_level([_finding("cnic")], tax) == 3


def test_a_tenant_rule_cannot_lower_a_builtin_rank() -> None:
    """Custom rules extend the table; they must not weaken the spec ranks."""
    tax = Taxonomy.for_tenant({"card_number": 1})
    assert aggregate_level([_finding("card_number")], tax) == 4


def test_a_genuinely_unknown_type_still_fails_loud() -> None:
    tax = Taxonomy.for_tenant({})
    with pytest.raises(ValueError, match="unknown entity_type"):
        tax.rank_for(_finding("never_registered"))
