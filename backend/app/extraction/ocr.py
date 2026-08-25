"""OCR stub — implementation arrives with the Tesseract wave.

This module only detects *whether* a job needs OCR (scanned PDF probe) so
workers can route to the dedicated ocr queue without invoking a handler.
"""

from app.extraction.base import ExtractedDocument
from app.extraction.pdf import has_text_layer


class OcrHandler:
    """Placeholder handler; never registered while OCR is unimplemented."""

    def extract(self, data: bytes) -> ExtractedDocument:
        raise NotImplementedError("OCR arrives with Tesseract wave; job routed to ocr queue")


def requires_ocr(data: bytes) -> bool:
    """True when ``data`` is a PDF without a usable text layer."""
    return not has_text_layer(data)
