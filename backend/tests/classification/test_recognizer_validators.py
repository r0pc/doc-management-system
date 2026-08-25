"""Truth tables for recogniser validators and the shared context scorer.

Validators are REAL this phase (invariant #10: pattern + structural validator +
context words); scan() bodies are placeholders until the rules wave. Canonical
formats mirror ml/entities.py per artifact_contract.md — mirrored, not re-derived.
"""

import pytest

from app.classification.rules.base import WINDOW, Recognizer, score_with_context
from app.classification.rules.recognizers import (
    BankAccountRecognizer,
    CardNumberRecognizer,
    CnicRecognizer,
    PassportRecognizer,
)

# ---------------------------------------------------------------------------
# CNIC validator — spec §3.2 verbatim: province digit in {1,2,3,4,5,7,8};
# 0/6/9 are invalid province codes.
# ---------------------------------------------------------------------------


def cnic(province: str) -> str:
    return f"{province}2101-1234567-8"


@pytest.mark.parametrize("province", ["1", "2", "3", "4", "5", "7", "8"])
def test_cnic_accepts_valid_provinces(province: str) -> None:
    assert CnicRecognizer().validate(cnic(province)) is True


@pytest.mark.parametrize("province", ["0", "6", "9"])
def test_cnic_rejects_invalid_provinces(province: str) -> None:
    assert CnicRecognizer().validate(cnic(province)) is False


@pytest.mark.parametrize(
    "bad",
    [
        "4210-1234567-8",  # short first group -> 12 digits after stripping
        "42101-12345678-8",  # long middle group -> 14 digits after stripping
        "4210A-1234567-8",  # letter in digit group
        "",
    ],
)
def test_cnic_rejects_malformed_candidates(bad: str) -> None:
    assert CnicRecognizer().validate(bad) is False


# ---------------------------------------------------------------------------
# Card validator — canonical format is 16 digits passing Luhn (entities.py);
# spaces/hyphens are normalised away before validation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("4111111111111111", True),  # classic Luhn vector
        ("4111111111111112", False),  # off-by-one check digit
        ("4111 1111 1111 1111", True),  # spaced variant normalises to the same digits
        ("4111-1111-1111-1111", True),  # hyphenated variant
        ("411111111111111", False),  # 15 digits: right idea, wrong length
        ("41111111111111111", False),  # 17 digits
        ("41111111111111x1", False),  # non-digit survives normalisation
        ("", False),
    ],
)
def test_card_validator_truth_table(candidate: str, expected: bool) -> None:
    assert CardNumberRecognizer().validate(candidate) is expected


# ---------------------------------------------------------------------------
# Passport validator — canonical shape [A-Z]{2}\d{7} (make_passport).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("KP1234567", True),
        ("AB0000000", True),
        ("kp1234567", False),  # lowercase letters
        ("KP123456", False),  # six digits
        ("KP12345678", False),  # eight digits
        ("K1234567", False),  # one letter
        ("K11234567", False),  # digit among the letters
        ("", False),
    ],
)
def test_passport_validator_truth_table(candidate: str, expected: bool) -> None:
    assert PassportRecognizer().validate(candidate) is expected


# ---------------------------------------------------------------------------
# Account validator — PK + two uppercase letters + thirteen digits; length and
# prefix only, NO IBAN checksum in phase 1 (documented deviation).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("PKAB1234567890123", True),
        ("PKXY0000000000000", True),
        ("pkAB1234567890123", False),  # lowercase prefix
        ("XXAB1234567890123", False),  # wrong country prefix
        ("PKAB123456789012", False),  # twelve digits
        ("PKAB12345678901234", False),  # fourteen digits
        ("PK121234567890123", False),  # digits where letters belong
        ("PKAB12345678901a3", False),
        ("", False),
    ],
)
def test_account_validator_truth_table(candidate: str, expected: bool) -> None:
    assert BankAccountRecognizer().validate(candidate) is expected


# ---------------------------------------------------------------------------
# score_with_context — spec §3.2 semantics pinned as a truth table:
# 0 hits -> base 0.4; 1 hit -> 0.7; >= 2 hits -> capped 0.9; ±WINDOW boundary.
# ---------------------------------------------------------------------------

CARD_WORDS = ["card", "credit", "debit"]


def test_window_constant_is_fifty() -> None:
    assert Recognizer.WINDOW == WINDOW == 50


def test_zero_context_hits_score_base() -> None:
    text = "x" * 30 + "4111111111111111" + "x" * 30
    span = (30, 46)
    assert score_with_context(text, span, CARD_WORDS) == pytest.approx(0.4)


def test_one_context_hit_scores_seven() -> None:
    text = "credit card no 4111111111111111"
    span = (15, 31)
    assert score_with_context(text, span, ["card"]) == pytest.approx(0.7)


def test_two_context_hits_score_nine() -> None:
    text = "credit card payment 4111111111111111"
    span = (19, 35)
    assert score_with_context(text, span, ["card", "payment"]) == pytest.approx(0.9)


def test_many_hits_cap_at_boost_to() -> None:
    text = "card card card card 4111111111111111"
    span = (20, 36)
    assert score_with_context(text, span, ["card"], boost_to=0.9) == pytest.approx(0.9)


def test_context_word_just_inside_right_boundary_boosts() -> None:
    # "card" occupies offsets end+45..end+48, fully inside [end, end+50).
    text = "4111111111111111" + "." * 45 + "card"
    assert score_with_context(text, (0, 16), ["card"]) == pytest.approx(0.7)


def test_context_word_starting_at_end_plus_window_is_outside() -> None:
    # "card" starts at offset end+50: the right slice ends at end+49.
    text = "4111111111111111" + "." * 50 + "card"
    assert score_with_context(text, (0, 16), ["card"]) == pytest.approx(0.4)


def test_context_word_just_inside_left_boundary_boosts() -> None:
    # "card" occupies offsets start-46..start-43, fully inside [start-50, start).
    text = "card" + "." * 42 + "4111111111111111"
    start = len(text) - 16
    assert score_with_context(text, (start, start + 16), ["card"]) == pytest.approx(0.7)


def test_context_word_ending_before_left_window_is_outside() -> None:
    # "card" ends at offset start-51: the left slice begins at start-50.
    text = "card" + "." * 51 + "4111111111111111"
    start = len(text) - 16
    assert score_with_context(text, (start, start + 16), ["card"]) == pytest.approx(0.4)


def test_multiword_context_term_matches_case_insensitively() -> None:
    text = "Card No: 4111111111111111"
    assert score_with_context(text, (9, 25), ["card no"]) == pytest.approx(0.7)
