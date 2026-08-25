"""PDF text extraction via pymupdf, with scanned-PDF detection.

``NeedsOcrError`` is raised exclusively here: a PDF whose text layer is
thinner than the threshold is routed to the dedicated ocr queue.
"""

from typing import TYPE_CHECKING, Final

from app.extraction.base import (
    ExtractedDocument,
    NeedsOcrError,
    PageText,
    ParserUnavailable,
)
from app.extraction.sniff import MIME_PDF

_MIN_TEXT_CHARS: Final = 20

if TYPE_CHECKING:
    from pymupdf import Document


def _open_pdf(data: bytes) -> Document:
    """Open a PDF document, lazy-importing pymupdf (parser extras optional)."""
    try:
        import pymupdf
    except ImportError as exc:
        raise ParserUnavailable("pymupdf is not installed") from exc
    return pymupdf.Document(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]  # pymupdf 1.28 ships partial stubs; Document.__init__ untyped upstream


def has_text_layer(data: bytes) -> bool:
    """True when the PDF carries at least ``_MIN_TEXT_CHARS`` of extractable text."""
    with _open_pdf(data) as document:
        total = sum(len(page.get_text().strip()) for page in document.pages())
    return total >= _MIN_TEXT_CHARS


class PdfHandler:
    """Extracts per-page text; thin text layers raise NeedsOcrError."""

    def extract(self, data: bytes) -> ExtractedDocument:
        with _open_pdf(data) as document:
            pages = [
                PageText(page_no=page_no, text=page.get_text())
                for page_no, page in enumerate(document.pages(), start=1)
            ]
        text = "\n\n".join(page.text for page in pages)
        if len(text.strip()) < _MIN_TEXT_CHARS:
            raise NeedsOcrError("pdf text layer empty or too thin; route job to the ocr queue")
        return ExtractedDocument(
            text=text,
            pages=pages,
            mime_sniffed=MIME_PDF,
            char_count=len(text),
            ocr_used=False,
        )
