"""The four phase-1 PII recognisers: REAL validators, STUBBED scanners.

Canonical formats mirror ml/entities.py per artifact_contract.md — mirrored,
not re-derived. Validators and patterns are production-ready now; every scan()
body is a placeholder until the rules wave (user-locked scope, four types).
"""

from __future__ import annotations

import re
from typing import ClassVar, Final

from app.classification.rules.base import Recognizer, score_with_context
from app.domain.models import Finding

# Mirrors ml/entities.py constants (single source of truth for the formats).
CARD_LENGTH: Final[int] = 16
CNIC_PROVINCE_DIGITS: Final[frozenset[str]] = frozenset("1234578")  # 0/6/9 invalid
ACCOUNT_PREFIX: Final[str] = "PK"
ACCOUNT_LENGTH: Final[int] = len(ACCOUNT_PREFIX) + 2 + 13  # PK + 2 letters + 13 digits


def luhn(digits: str) -> bool:
    """Luhn checksum over a digit string (mirrors ml/entities.luhn_valid arithmetic)."""
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


class CardNumberRecognizer(Recognizer):
    """Payment-card candidates; canonical format is 16 digits passing Luhn."""

    entity_type: ClassVar[str] = "card_number"
    pattern: ClassVar[re.Pattern[str]] = re.compile(r"\b\d{13,19}\b")
    context_words: ClassVar[list[str]] = [
        "card",
        "credit",
        "debit",
        "visa",
        "mastercard",
        "card no",
        "payment",
    ]

    def validate(self, match_text: str) -> bool:
        digits = match_text.replace(" ", "").replace("-", "")
        return len(digits) == CARD_LENGTH and digits.isdigit() and luhn(digits)

    def scan(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for match in self.pattern.finditer(text):
            candidate = match.group()
            if not self.validate(candidate):
                continue
            span = match.span()
            score = score_with_context(text, span, self.context_words)
            findings.append(
                Finding(
                    entity_type=self.entity_type,
                    rule_id=self.__class__.__name__,
                    page_no=None,
                    char_start=span[0],
                    char_end=span[1],
                    score=score,
                )
            )
        return findings


class CnicRecognizer(Recognizer):
    """Pakistani CNIC 'PPPPPPPPP-#######-P'; province digit per spec §3.2."""

    entity_type: ClassVar[str] = "cnic"
    pattern: ClassVar[re.Pattern[str]] = re.compile(r"\b\d{5}-\d{7}-\d\b")
    context_words: ClassVar[list[str]] = ["cnic", "nic", "identity", "shanakhti", "card no"]

    def validate(self, match_text: str) -> bool:
        digits = match_text.replace("-", "")
        if len(digits) != 13 or not digits.isdigit():
            return False
        return digits[0] in CNIC_PROVINCE_DIGITS

    def scan(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for match in self.pattern.finditer(text):
            candidate = match.group()
            if not self.validate(candidate):
                continue
            span = match.span()
            score = score_with_context(text, span, self.context_words)
            findings.append(
                Finding(
                    entity_type=self.entity_type,
                    rule_id=self.__class__.__name__,
                    page_no=None,
                    char_start=span[0],
                    char_end=span[1],
                    score=score,
                )
            )
        return findings


class PassportRecognizer(Recognizer):
    """Passport numbers; canonical shape is two uppercase letters + seven digits."""

    entity_type: ClassVar[str] = "passport_number"
    pattern: ClassVar[re.Pattern[str]] = re.compile(r"\b[A-Z]{2}\d{7}\b")
    context_words: ClassVar[list[str]] = ["passport", "passport no", "travel document"]

    def validate(self, match_text: str) -> bool:
        # The canonical format (make_passport) carries no checksum; the shape
        # itself is the structural validator.
        return re.fullmatch(r"[A-Z]{2}\d{7}", match_text) is not None

    def scan(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for match in self.pattern.finditer(text):
            candidate = match.group()
            if not self.validate(candidate):
                continue
            span = match.span()
            score = score_with_context(text, span, self.context_words)
            findings.append(
                Finding(
                    entity_type=self.entity_type,
                    rule_id=self.__class__.__name__,
                    page_no=None,
                    char_start=span[0],
                    char_end=span[1],
                    score=score,
                )
            )
        return findings


class BankAccountRecognizer(Recognizer):
    """IBAN-style Pakistani account 'PK' + two letters + thirteen digits.

    Phase 1 validates length and prefix only; NO IBAN checksum (documented
    deviation in artifact_contract.md).
    """

    entity_type: ClassVar[str] = "bank_account"
    pattern: ClassVar[re.Pattern[str]] = re.compile(r"\bPK[A-Z]{2}\d{13}\b")
    context_words: ClassVar[list[str]] = ["iban", "account", "account no", "bank"]

    def validate(self, match_text: str) -> bool:
        if len(match_text) != ACCOUNT_LENGTH or not match_text.startswith(ACCOUNT_PREFIX):
            return False
        letters = match_text[2:4]
        return (
            letters.isascii()
            and letters.isalpha()
            and letters.isupper()
            and match_text[4:].isdigit()
        )

    def scan(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for match in self.pattern.finditer(text):
            candidate = match.group()
            if not self.validate(candidate):
                continue
            span = match.span()
            score = score_with_context(text, span, self.context_words)
            findings.append(
                Finding(
                    entity_type=self.entity_type,
                    rule_id=self.__class__.__name__,
                    page_no=None,
                    char_start=span[0],
                    char_end=span[1],
                    score=score,
                )
            )
        return findings
