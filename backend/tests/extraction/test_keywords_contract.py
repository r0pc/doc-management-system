"""Keyword extractor contracts: determinism (#6) and cross-implementation shape."""

import dataclasses
import importlib.util
import json

import pytest

from app.extraction.base import ExtractedKeywords, ParserUnavailable
from app.extraction.keywords import FrequencyFallback, SpacyKeywordExtractor

SAMPLE = (
    "Contract renewal contract review contract audit invoice invoice payment payment ledger 2024 Q3"
)

EXPECTED_TERMS = [
    ("contract", 1.0),
    ("invoice", 0.6667),
    ("payment", 0.6667),
    ("2024", 0.3333),
    ("audit", 0.3333),
    ("ledger", 0.3333),
    ("q3", 0.3333),
    ("renewal", 0.3333),
    ("review", 0.3333),
]


def test_identical_text_gives_byte_identical_terms() -> None:
    first = FrequencyFallback().extract(SAMPLE)
    second = FrequencyFallback().extract(SAMPLE)
    assert json.dumps(first.terms) == json.dumps(second.terms)
    assert first == second


def test_ranking_normalisation_and_tie_breaking() -> None:
    assert FrequencyFallback().extract(SAMPLE).terms == EXPECTED_TERMS


def test_stopwords_and_case_are_dropped() -> None:
    result = FrequencyFallback().extract("The THE the Contract and an")
    assert [term for term, _ in result.terms] == ["contract"]


def test_top_n_limits_output() -> None:
    assert FrequencyFallback(top_n=2).extract(SAMPLE).terms == EXPECTED_TERMS[:2]


def test_empty_text_yields_empty_terms() -> None:
    assert FrequencyFallback().extract("").terms == []


def test_extractor_name_is_stable() -> None:
    assert FrequencyFallback().extract(SAMPLE).extractor_name == "frequency-fallback"


class ScriptedExtractor:
    """A second KeywordExtractor implementation for the shape contract (#6)."""

    def extract(self, text: str) -> ExtractedKeywords:
        return ExtractedKeywords(terms=[("scripted", 1.0)], extractor_name="scripted-test")


def test_keywords_shape_stable_across_implementations() -> None:
    """Downstream consumers rely on shape, never on a specific extractor."""
    results = [
        FrequencyFallback().extract(SAMPLE),
        ScriptedExtractor().extract(SAMPLE),
    ]
    assert [field.name for field in dataclasses.fields(ExtractedKeywords)] == [
        "terms",
        "extractor_name",
    ]
    for result in results:
        assert isinstance(result, ExtractedKeywords)
        assert isinstance(result.terms, list)
        for term, score in result.terms:
            assert isinstance(term, str)
            assert isinstance(score, float)
        assert isinstance(result.extractor_name, str)


_spacy_installed = importlib.util.find_spec("spacy") is not None


@pytest.mark.skipif(_spacy_installed, reason="spaCy installed; guard path unreachable")
def test_spacy_extractor_guard_raises_parser_unavailable() -> None:
    with pytest.raises(ParserUnavailable):
        SpacyKeywordExtractor()
