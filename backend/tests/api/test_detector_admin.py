# backend/tests/api/test_detector_admin.py
"""Admin detector CRUD, gated and ReDoS-guarded."""

from __future__ import annotations

from typing import Any

import pytest

from app.classification.rules.safety import PatternUnsafeError, assert_pattern_safe

GOOD = {
    "entity_type": "company_api_key",
    "pattern": r"\bAKIA[0-9A-Z]{16}\b",
    "context_words": ["aws", "secret"],
    "validator_kind": "prefix_charset",
    "validator_config": {"prefix": "AKIA", "length": 20, "charset": "A-Z0-9"},
    "level_rank": 4,
}


@pytest.mark.parametrize(
    "evil",
    [r"(a+)+$", r"(a|a)*$", r"(.*a){20}", r"([a-zA-Z]+)*$"],
    ids=["nested_plus", "alt_overlap", "repeated_group", "nested_star"],
)
def test_catastrophic_patterns_are_refused(evil: str) -> None:
    with pytest.raises(PatternUnsafeError):
        assert_pattern_safe(evil)


@pytest.mark.parametrize(
    "safe", [r"\bAKIA[0-9A-Z]{16}\b", r"\d{5}-\d{7}-\d", r"sk_live_[a-z0-9]{24}"]
)
def test_reasonable_patterns_are_allowed(safe: str) -> None:
    assert_pattern_safe(safe)


def test_create_requires_manage_taxonomy(client_factory: Any) -> None:
    viewer = client_factory(role="viewer")
    assert viewer.post("/v1/admin/detectors", json=GOOD).status_code == 403


def test_create_rejects_a_rule_without_a_validator(client_factory: Any) -> None:
    """#10 at the API boundary, not only in the schema."""
    admin = client_factory(role="admin")
    bad = {**GOOD}
    del bad["validator_kind"]
    assert admin.post("/v1/admin/detectors", json=bad).status_code in (400, 422)


def test_create_rejects_empty_context_words(client_factory: Any) -> None:
    admin = client_factory(role="admin")
    assert admin.post("/v1/admin/detectors", json={**GOOD, "context_words": []}).status_code in (
        400,
        422,
    )


def test_create_rejects_an_unsafe_pattern(client_factory: Any) -> None:
    admin = client_factory(role="admin")
    response = admin.post("/v1/admin/detectors", json={**GOOD, "pattern": r"(a+)+$"})
    assert response.status_code == 422
    assert "pattern" in response.json()["detail"].lower()


def test_preview_returns_offsets_never_matched_text(client_factory: Any) -> None:
    """#12 holds even in an admin preview."""
    admin = client_factory(role="admin")
    body = admin.post(
        "/v1/admin/detectors/preview",
        json={**GOOD, "sample_text": "aws secret AKIA" + "J" * 16},
    ).json()
    assert body["matches"][0]["char_start"] >= 0
    serialised = str(body)
    assert "AKIAJ" not in serialised
