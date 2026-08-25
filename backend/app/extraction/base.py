"""Extraction contracts: value objects, protocols and failure taxonomy.

Single source of truth imported by handlers, the registry, keyword extractors
and the workers. Handlers receive bytes only — invariant #19 forbids filename
parameters anywhere in this package.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PageText:
    """Text of one physical page (docx/xlsx use a single pseudo-page)."""

    page_no: int
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    """Result of one text-extraction pass over a blob."""

    text: str
    pages: list[PageText]
    mime_sniffed: str
    char_count: int
    ocr_used: bool


@dataclass(frozen=True)
class ExtractedKeywords:
    """Weighted terms plus the extractor that produced them (#6 shape contract)."""

    terms: list[tuple[str, float]]
    extractor_name: str


class ParserUnavailable(Exception):  # noqa: N818  # frozen contract name from the wave spec
    """A lazy-imported parser library is missing from the environment."""


class NeedsOcrError(Exception):
    """Text layer is empty/thin — the job must be handed to the ocr queue."""


class UnknownMimeError(Exception):
    """Byte content matched no known signature during sniffing."""


class ExtractionHandler(Protocol):
    """Structural interface every mime handler satisfies."""

    def extract(self, data: bytes) -> ExtractedDocument: ...


class KeywordExtractor(Protocol):
    """Structural interface every keyword extractor satisfies."""

    def extract(self, text: str) -> ExtractedKeywords: ...
