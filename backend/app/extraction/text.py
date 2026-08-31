"""Plain text extraction: decodes text files and provides page/line structure.

A plain text file is reported as a single logical page (page_no=1).
"""

from __future__ import annotations

from app.extraction.base import ExtractedDocument, PageText
from app.extraction.sniff import MIME_TEXT


class TextHandler:
    """Extracts text content by decoding bytes as UTF-8 (with Latin-1 fallback)."""

    def extract(self, data: bytes) -> ExtractedDocument:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1", errors="replace")
        return ExtractedDocument(
            text=text,
            pages=[PageText(page_no=1, text=text)],
            mime_sniffed=MIME_TEXT,
            char_count=len(text),
            ocr_used=False,
        )
