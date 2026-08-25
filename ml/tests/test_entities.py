"""Canonical synthetic entity format tests (entities.py is the single source)."""

import random
import re

import pytest

from entities import SPECS, luhn_valid, make_account, make_card, make_cnic, make_passport

VALID_PROVINCES = {"1", "2", "3", "4", "5", "7", "8"}
CNIC_RE = re.compile(r"^\d{5}-\d{7}-\d$")
PASSPORT_RE = re.compile(r"^[A-Z]{2}\d{7}$")
ACCOUNT_RE = re.compile(r"^PK[A-Z]{2}\d{13}$")


class TestLuhn:
    def test_luhn_accepts_known_valid_vectors(self):
        assert luhn_valid("4111111111111111") is True
        assert luhn_valid("4242424242424242") is True

    def test_luhn_rejects_known_invalid_vectors(self):
        assert luhn_valid("4111111111111112") is False
        assert luhn_valid("4242424242424241") is False
        assert luhn_valid("") is False
        assert luhn_valid("411111111111111") is False  # 15 digits: wrong length

    def test_luhn_rejects_non_digit_input(self):
        assert luhn_valid("4111-1111-1111-1111") is False


class TestMakeCard:
    def test_generated_cards_always_pass_luhn_with_16_digits(self):
        rng = random.Random(7)
        cards = {make_card(rng) for _ in range(100)}
        assert len(cards) >= 90  # effectively unique draws
        for card in cards:
            assert len(card) == 16
            assert card.isdigit()
            assert luhn_valid(card) is True


class TestMakeCnic:
    def test_format_matches_canonical_shape(self):
        rng = random.Random(1)
        for _ in range(300):
            assert CNIC_RE.match(make_cnic(rng))

    @pytest.mark.parametrize("banned", ["0", "6", "9"])
    def test_province_digit_never_uses_invalid_codes(self, banned: str):
        rng = random.Random(2)
        for _ in range(300):
            cnic = make_cnic(rng)
            assert cnic[0] != banned
            assert cnic[0] in VALID_PROVINCES


class TestMakePassport:
    def test_shape_is_two_uppercase_letters_then_seven_digits(self):
        rng = random.Random(3)
        for _ in range(200):
            assert PASSPORT_RE.match(make_passport(rng))


class TestMakeAccount:
    def test_shape_is_pk_prefix_two_letters_thirteen_digits(self):
        rng = random.Random(4)
        for _ in range(200):
            iban = make_account(rng)
            assert len(iban) == 17
            assert ACCOUNT_RE.match(iban)


class TestSpecs:
    def test_specs_match_spec_section_3_7_verbatim(self):
        assert SPECS == {
            "restricted": {"cnic": (3, 8), "salary": (2, 6), "account": (1, 3)},
            "confidential": {"cnic": (1, 2), "salary": (0, 1), "account": (0, 0)},
            "internal": {"cnic": (0, 0), "salary": (0, 0), "account": (0, 0)},
        }
