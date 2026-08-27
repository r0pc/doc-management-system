"""Registry contract: exactly four PII entity types, placeholder scans pinned.

The PII scope is locked this phase — bank_account, card_number, passport_number,
cnic — and every scan() body is a stub returning [] until the rules wave. These
tests pin the placeholder so a surprise scanner cannot sneak in.
"""

from app.classification.rules.base import Recognizer
from app.classification.rules.registry import ENTITY_TYPES, build_recognizers, iter_recognizers

# A bank-statement-like text carrying one of every entity plus context words.
BANK_STATEMENT_LIKE = (
    "Monthly statement. Account no PKAB1234567890123. "
    "Credit card no 4111111111111111. "
    "CNIC 42101-1234567-8. Passport KP1234567."
)


def test_entity_types_tuple_is_exactly_the_locked_scope() -> None:
    assert ENTITY_TYPES == ("bank_account", "card_number", "passport_number", "cnic")
    assert len(ENTITY_TYPES) == 4


def test_build_recognizers_maps_every_entity_type_to_one_instance() -> None:
    recognizers = build_recognizers()
    assert set(recognizers) == set(ENTITY_TYPES)
    assert len(recognizers) == 4
    for entity_type, recognizer in recognizers.items():
        assert isinstance(recognizer, Recognizer)
        assert recognizer.entity_type == entity_type


def test_iter_recognizers_yields_all_four() -> None:
    assert len(list(iter_recognizers())) == 4


def test_every_scan_returns_findings() -> None:
    for recognizer in build_recognizers().values():
        findings = recognizer.scan(BANK_STATEMENT_LIKE)
        assert len(findings) == 1
        assert findings[0].entity_type == recognizer.entity_type


def test_patterns_compile_and_match_their_canonical_shape() -> None:
    samples = {
        "bank_account": "PKAB1234567890123",
        "card_number": "4111111111111111",
        "passport_number": "KP1234567",
        "cnic": "42101-1234567-8",
    }
    for recognizer in build_recognizers().values():
        match = recognizer.pattern.search(BANK_STATEMENT_LIKE)
        assert match is not None, recognizer.entity_type
        assert recognizer.validate(samples[recognizer.entity_type]) is True
