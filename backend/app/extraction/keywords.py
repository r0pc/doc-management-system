"""Keyword extractors: deterministic frequency fallback + spaCy guard.

``FrequencyFallback`` is the always-available implementation downstream
consumers may rely on; output is fully deterministic (sorted by score desc,
then term asc) so identical text yields byte-identical terms (#6).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Final

from app.extraction.base import ExtractedKeywords, ParserUnavailable

_WORD_PATTERN: Final = r"[a-z0-9]+"
_DEFAULT_TOP_N: Final = 20
_SCORE_DECIMALS: Final = 4
_FALLBACK_NAME: Final = "frequency-fallback"
_SPACY_NAME: Final = "spacy-en-core-web-sm"

# Curated English stopword set — hardcoded so behaviour never depends on a
# downloadable corpus.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "when",
        "at",
        "by",
        "for",
        "with",
        "about",
        "against",
        "between",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "to",
        "from",
        "up",
        "down",
        "in",
        "out",
        "on",
        "off",
        "over",
        "under",
        "again",
        "further",
        "once",
        "here",
        "there",
        "all",
        "any",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "can",
        "will",
        "just",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "having",
        "do",
        "does",
        "did",
        "doing",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "them",
        "his",
        "her",
        "its",
        "their",
        "this",
        "that",
        "these",
        "those",
        "of",
        "as",
    }
)


def _normalised_terms(counts: Counter[str], top_n: int | None = None) -> list[tuple[str, float]]:
    """Score counts against the max, sorted by (-score, term) for determinism."""
    if not counts:
        return []
    max_count = max(counts.values())
    scored = sorted(
        ((term, round(count / max_count, _SCORE_DECIMALS)) for term, count in counts.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return scored if top_n is None else scored[:top_n]


class FrequencyFallback:
    """Token-frequency scorer with max-normalised weights."""

    def __init__(self, top_n: int = _DEFAULT_TOP_N) -> None:
        self._top_n = top_n

    def extract(self, text: str) -> ExtractedKeywords:
        counts = Counter(
            token for token in re.findall(_WORD_PATTERN, text.lower()) if token not in _STOPWORDS
        )
        return ExtractedKeywords(
            terms=_normalised_terms(counts, top_n=self._top_n),
            extractor_name=_FALLBACK_NAME,
        )


class SpacyKeywordExtractor:
    """spaCy-backed extractor; construction fails closed when spaCy is absent."""

    def __init__(self) -> None:
        try:
            import spacy  # type: ignore[import-not-found]  # optional extra; guarded at runtime
        except ImportError as exc:
            raise ParserUnavailable("spaCy is not installed") from exc
        self._nlp = spacy.load("en_core_web_sm")

    def extract(self, text: str) -> ExtractedKeywords:
        doc = self._nlp(text)
        counts = Counter(
            token.lemma_.lower() for token in doc if token.is_alpha and not token.is_stop
        )
        return ExtractedKeywords(terms=_normalised_terms(counts), extractor_name=_SPACY_NAME)
