"""Structural validators for configurable recognisers (#10).

A bare regex is not an acceptable recogniser. These functions validate
candidates before any finding is emitted. Each returns bool and never raises
on odd input.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Callable
from typing import Any

from app.classification.rules.recognizers import luhn as luhn_valid


def validate_luhn(text: str, config: dict[str, Any] | None = None) -> bool:
    digits = text.replace(" ", "").replace("-", "")
    if not digits.isdigit():
        return False
    return luhn_valid(digits)


def validate_mod97(text: str, config: dict[str, Any] | None = None) -> bool:
    """ISO 7064 Mod 97-10 checksum (IBAN-style)."""
    cleaned = text.replace(" ", "").replace("-", "").upper()
    if len(cleaned) < 4:
        return False
    # Move the first 4 chars to the end (e.g. country code + check digits)
    rearranged = cleaned[4:] + cleaned[:4]
    numeric = ""
    for char in rearranged:
        if char.isdigit():
            numeric += char
        elif "A" <= char <= "Z":
            numeric += str(ord(char) - ord("A") + 10)
        else:
            return False
    try:
        return int(numeric) % 97 == 1
    except (ValueError, OverflowError):
        return False


def validate_entropy(text: str, config: dict[str, Any] | None = None) -> bool:
    """Shannon entropy (bits per character) over text."""
    if not text:
        return False
    min_bits = float(config.get("min_bits_per_char", 3.0)) if config else 3.0
    counts = Counter(text)
    length = len(text)
    entropy = -sum((count / length) * math.log2(count / length) for count in counts.values())
    return entropy >= min_bits


def validate_prefix_charset(text: str, config: dict[str, Any] | None = None) -> bool:
    if not config:
        return False
    prefix = config.get("prefix")
    if prefix and not text.startswith(prefix):
        return False
    length = config.get("length")
    if length is not None and len(text) != length:
        return False
    charset = config.get("charset")
    if charset:
        charset_set = set(charset)
        if any(c not in charset_set for c in text):
            return False
    return True


def validate_checksum_suffix(text: str, config: dict[str, Any] | None = None) -> bool:
    if not config or len(text) < 4:
        return False
    suffix_len = int(config.get("length", 4))
    algo = config.get("algorithm", "sha256")
    if len(text) <= suffix_len:
        return False
    payload = text[:-suffix_len].encode("utf-8")
    suffix = text[-suffix_len:].lower()
    if algo == "sha256":
        expected = hashlib.sha256(payload).hexdigest()[:suffix_len].lower()
        return suffix == expected
    return False


VALIDATORS: dict[str, Callable[[str, dict[str, Any]], bool]] = {
    "luhn": validate_luhn,
    "mod97": validate_mod97,
    "entropy": validate_entropy,
    "prefix_charset": validate_prefix_charset,
    "checksum_suffix": validate_checksum_suffix,
}
