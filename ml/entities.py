"""Canonical synthetic entity formats for the DMS training corpus.

Single source of truth: backend validators mirror these formats (see artifact_contract.md).
All values are synthetic; generated with Faker('en_PK') pools upstream. No real personal data.
"""

import random
import string

CNIC_PROVINCE_DIGITS = "1234578"  # 0, 6, 9 are invalid province codes (spec §3.2 validator)
CARD_LENGTH = 16
PASSPORT_LETTERS = 2
PASSPORT_DIGITS = 7
ACCOUNT_PREFIX = "PK"
ACCOUNT_LETTERS = 2
ACCOUNT_DIGITS = 13

# spec §3.7 verbatim intent: per-level entity count ranges (inclusive).
SPECS: dict[str, dict[str, tuple[int, int]]] = {
    "restricted": {"cnic": (3, 8), "salary": (2, 6), "account": (1, 3)},
    "confidential": {"cnic": (1, 2), "salary": (0, 1), "account": (0, 0)},
    "internal": {"cnic": (0, 0), "salary": (0, 0), "account": (0, 0)},
}

# Card counts are derived, not part of SPECS: restricted records carry 1-2 cards, others none.
CARD_RANGE_BY_LEVEL: dict[str, tuple[int, int]] = {
    "restricted": (1, 2),
    "confidential": (0, 0),
    "internal": (0, 0),
}


def luhn_valid(digits: str) -> bool:
    """Return True when *digits* (length CARD_LENGTH) satisfies the Luhn checksum."""
    if len(digits) != CARD_LENGTH or not digits.isdigit():
        return False
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _luhn_check_digit(first_fifteen: str) -> str:
    total = 0
    for position, char in enumerate(reversed(first_fifteen)):
        value = int(char)
        if position % 2 == 0:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return str((10 - total % 10) % 10)


def make_cnic(rng: random.Random) -> str:
    """Synthetic CNIC: 'P####-#######-#' (5-7-1 groups) with province P in {1,2,3,4,5,7,8}."""
    province = rng.choice(CNIC_PROVINCE_DIGITS)
    group_one = "".join(rng.choice(string.digits) for _ in range(4))
    family = "".join(rng.choice(string.digits) for _ in range(7))
    check = rng.choice(string.digits)
    return f"{province}{group_one}-{family}-{check}"


def make_card(rng: random.Random) -> str:
    """Synthetic 16-digit payment card number that passes Luhn."""
    body = "".join(rng.choice(string.digits) for _ in range(CARD_LENGTH - 1))
    return body + _luhn_check_digit(body)


def make_passport(rng: random.Random) -> str:
    """Synthetic passport number: two uppercase letters then seven digits (e.g. KP1234567)."""
    letters = "".join(rng.choice(string.ascii_uppercase) for _ in range(PASSPORT_LETTERS))
    digits = "".join(rng.choice(string.digits) for _ in range(PASSPORT_DIGITS))
    return f"{letters}{digits}"


def make_account(rng: random.Random) -> str:
    """Synthetic IBAN-style account: 'PK' + two uppercase letters + thirteen digits.

    Phase 1 mirrors length + prefix only; no IBAN checksum is computed or validated
    (documented deviation, see artifact_contract.md).
    """
    letters = "".join(rng.choice(string.ascii_uppercase) for _ in range(ACCOUNT_LETTERS))
    digits = "".join(rng.choice(string.digits) for _ in range(ACCOUNT_DIGITS))
    return f"{ACCOUNT_PREFIX}{letters}{digits}"
