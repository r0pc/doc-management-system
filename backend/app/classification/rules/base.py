"""Recogniser contract shared by every PII recogniser.

Invariant #10: a recogniser is a pattern PLUS a structural validator PLUS
context words scored in a +/-50 character window — a bare regex is not
acceptable. The scoring helper below is real now so the phase-2 scanners and
their tests pin identical semantics (spec §3.2).
"""

import re
from abc import ABC, abstractmethod
from typing import ClassVar, Final

from app.domain.models import Finding

#: Spec §3.2 context half-window, in characters, on each side of a match span.
WINDOW: Final[int] = 50


def score_with_context(
    text: str,
    match_span: tuple[int, int],
    context_words: list[str],
    window: int = WINDOW,
    base: float = 0.4,
    boost_to: float = 0.9,
) -> float:
    """Deterministic context score for one candidate match span.

    Counts case-insensitive occurrences of the context words within *window*
    characters on either side of the span (span itself excluded), then scores:
    zero hits -> ``base`` (0.4); each of the first two hits adds 0.2 above a
    0.5 floor, capped at ``boost_to`` — concretely 1 hit -> 0.7, >= 2 -> 0.9.
    Pure: no I/O, no clock, fully reproducible for tests and audit.
    """
    start, end = match_span
    nearby = (text[max(0, start - window) : start] + text[end : end + window]).lower()
    hits = sum(nearby.count(word.lower()) for word in context_words)
    if hits == 0:
        return base
    return min(0.5 + 0.2 * min(hits, 2), boost_to)


class Recognizer(ABC):
    """Contract every entity recogniser implements (invariant #10)."""

    #: Mirrors the module-level WINDOW; kept on the class for scanner call sites.
    WINDOW: Final[int] = 50

    entity_type: ClassVar[str]
    pattern: ClassVar[re.Pattern[str]]
    context_words: ClassVar[list[str]]

    @abstractmethod
    def validate(self, match_text: str) -> bool:
        """Structural validation of one candidate string."""

    @abstractmethod
    def scan(self, text: str) -> list[Finding]:
        """Offset-only findings for every validated match (never the text, #12)."""
