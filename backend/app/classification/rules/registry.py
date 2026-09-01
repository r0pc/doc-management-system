"""Registry of the locked phase-1 PII scope: exactly four entity types.

The scope is user-locked — bank_account, card_number, passport_number, cnic —
and nothing else registers until the rules wave reopens it.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, Final

from app.classification.rules.base import Recognizer
from app.classification.rules.configured import ConfiguredRecognizer
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


def build_recognizers_for_tenant(custom_rules: Sequence[Any] = ()) -> dict[str, Recognizer]:
    """Map entity_type -> recogniser instance for builtins + enabled tenant rules."""
    result: dict[str, Recognizer] = {
        "bank_account": BankAccountRecognizer(),
        "card_number": CardNumberRecognizer(),
        "passport_number": PassportRecognizer(),
        "cnic": CnicRecognizer(),
    }
    for rule in custom_rules:
        is_enabled = (
            getattr(rule, "is_enabled", True)
            if hasattr(rule, "is_enabled")
            else rule.get("is_enabled", True)
            if isinstance(rule, dict)
            else True
        )
        if not is_enabled:
            continue
        entity_type = (
            getattr(rule, "entity_type", None)
            if hasattr(rule, "entity_type")
            else rule.get("entity_type")
            if isinstance(rule, dict)
            else None
        )
        pattern = (
            getattr(rule, "pattern", None)
            if hasattr(rule, "pattern")
            else rule.get("pattern")
            if isinstance(rule, dict)
            else None
        )
        context_words = (
            getattr(rule, "context_words", None)
            if hasattr(rule, "context_words")
            else rule.get("context_words")
            if isinstance(rule, dict)
            else None
        )
        validator_kind = (
            getattr(rule, "validator_kind", None)
            if hasattr(rule, "validator_kind")
            else rule.get("validator_kind")
            if isinstance(rule, dict)
            else None
        )
        validator_config = (
            getattr(rule, "validator_config", None)
            if hasattr(rule, "validator_config")
            else rule.get("validator_config")
            if isinstance(rule, dict)
            else None
        )
        rule_id = (
            str(getattr(rule, "id", None) or getattr(rule, "rule_id", f"configured:{entity_type}"))
            if (hasattr(rule, "id") or hasattr(rule, "rule_id"))
            else str(rule.get("id") or rule.get("rule_id", f"configured:{entity_type}"))
            if isinstance(rule, dict)
            else f"configured:{entity_type}"
        )
        if entity_type and pattern and context_words and validator_kind:
            result[entity_type] = ConfiguredRecognizer(
                entity_type=entity_type,
                pattern=pattern,
                context_words=list(context_words),
                validator_kind=validator_kind,
                validator_config=validator_config,
                rule_id=rule_id,
            )
    return result


def iter_recognizers_for_tenant(custom_rules: Sequence[Any] = ()) -> Iterator[Recognizer]:
    """Iterate the registered recognisers for the tenant."""
    return iter(build_recognizers_for_tenant(custom_rules).values())


def build_recognizers() -> dict[str, Recognizer]:
    """Map entity_type -> recogniser instance for the locked four-type scope."""
    return build_recognizers_for_tenant(())


def iter_recognizers() -> Iterator[Recognizer]:
    """Iterate the registered recognisers in registry order."""
    return iter_recognizers_for_tenant(())
