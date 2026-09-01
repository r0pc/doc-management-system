# backend/tests/classification/test_configured_recognizer.py
"""#10: pattern + structural validator + context words. Never a bare regex."""

from __future__ import annotations

import pytest

from app.classification.rules.configured import ConfiguredRecognizer
from app.classification.rules.validators import VALIDATORS

KEY = "AKIA" + "J" * 16


def _rec(**over: object) -> ConfiguredRecognizer:
    base: dict[str, object] = {
        "entity_type": "company_api_key",
        "pattern": r"\bAKIA[0-9A-Z]{16}\b",
        "context_words": ["aws", "secret", "credential"],
        "validator_kind": "prefix_charset",
        "validator_config": {
            "prefix": "AKIA",
            "length": 20,
            "charset": "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        },
    }
    base.update(over)
    return ConfiguredRecognizer(**base)  # type: ignore[arg-type]


def test_a_validated_match_produces_an_offset_only_finding() -> None:
    text = f"the aws secret is {KEY} rotate it"
    findings = _rec().scan(text)
    assert len(findings) == 1
    f = findings[0]
    assert f.entity_type == "company_api_key"
    assert text[f.char_start : f.char_end] == KEY
    assert not hasattr(f, "text") and not hasattr(f, "value")  # #12


def test_context_words_raise_the_score() -> None:
    near = _rec().scan(f"aws secret credential {KEY}")[0]
    far = _rec().scan(f"unrelated prose {KEY} more prose")[0]
    assert near.score > far.score


def test_a_match_failing_the_validator_is_dropped() -> None:
    assert _rec().scan("AKIAJJJJ toolong not a key") == []


def test_an_unknown_validator_kind_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="unknown validator"):
        _rec(validator_kind="handwave")


def test_empty_context_words_are_rejected_at_construction() -> None:
    """#10 is not satisfiable without context words."""
    with pytest.raises(ValueError, match="context words"):
        _rec(context_words=[])


@pytest.mark.parametrize("kind", ["luhn", "mod97", "entropy", "prefix_charset"])
def test_every_advertised_validator_exists(kind: str) -> None:
    assert kind in VALIDATORS


def test_entropy_validator_separates_random_from_english() -> None:
    high = VALIDATORS["entropy"]("f3Kq9zXm2WpL7vB4nR8t", {"min_bits_per_char": 3.0})
    low = VALIDATORS["entropy"]("aaaaaaaaaaaaaaaaaaaa", {"min_bits_per_char": 3.0})
    assert high is True
    assert low is False
