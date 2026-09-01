"""Configurable recognisers that satisfy invariant #10.

A recogniser is a pattern PLUS a structural validator PLUS context words scored
in a +/-50 character window. A bare regex cannot be constructed here.
"""

from __future__ import annotations

import re
from typing import Any

from app.classification.rules.base import Recognizer, score_with_context
from app.classification.rules.validators import VALIDATORS
from app.domain.models import Finding


class ConfiguredRecognizer(Recognizer):
    """Recognizer configured from database rules or custom definitions."""

    def __init__(
        self,
        entity_type: str,
        pattern: str | re.Pattern[str],
        context_words: list[str],
        validator_kind: str,
        validator_config: dict[str, Any] | None = None,
        rule_id: str | None = None,
    ) -> None:
        if not context_words:
            msg = "context words cannot be empty (invariant #10)"
            raise ValueError(msg)
        if validator_kind not in VALIDATORS:
            msg = f"unknown validator kind {validator_kind!r}"
            raise ValueError(msg)

        self._entity_type = entity_type
        self._pattern = re.compile(pattern) if isinstance(pattern, str) else pattern
        self._context_words = list(context_words)
        self.validator_kind = validator_kind
        self.validator_config = validator_config or {}
        self.rule_id = rule_id or f"configured:{entity_type}"
        self._validator = VALIDATORS[validator_kind]

    @property
    def entity_type(self) -> str:
        return self._entity_type

    @property
    def pattern(self) -> re.Pattern[str]:
        return self._pattern

    @property
    def context_words(self) -> list[str]:
        return self._context_words

    def validate(self, match_text: str) -> bool:
        return self._validator(match_text, self.validator_config)

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
                    rule_id=self.rule_id,
                    page_no=None,
                    char_start=span[0],
                    char_end=span[1],
                    score=score,
                )
            )
        return findings
