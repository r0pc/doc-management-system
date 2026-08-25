"""Registry of the locked phase-1 PII scope: exactly four entity types.

The scope is user-locked — bank_account, card_number, passport_number, cnic —
and nothing else registers until the rules wave reopens it.
"""

from collections.abc import Iterator
from typing import Final

from app.classification.rules.base import Recognizer
from app.classification.rules.recognizers import (
    BankAccountRecognizer,
    CardNumberRecognizer,
    CnicRecognizer,
    PassportRecognizer,
)

ENTITY_TYPES: Final[tuple[str, ...]] = (
    "bank_account",
    "card_number",
    "passport_number",
    "cnic",
)


def build_recognizers() -> dict[str, Recognizer]:
    """Map entity_type -> recogniser instance for the locked four-type scope."""
    recognizers: list[Recognizer] = [
        BankAccountRecognizer(),
        CardNumberRecognizer(),
        PassportRecognizer(),
        CnicRecognizer(),
    ]
    return {recognizer.entity_type: recognizer for recognizer in recognizers}


def iter_recognizers() -> Iterator[Recognizer]:
    """Iterate the registered recognisers in registry order."""
    return iter(build_recognizers().values())
