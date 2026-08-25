"""Mime-to-handler dispatch. Workers call :func:`extract_document` only.

Failure taxonomy: :class:`UnknownMimeError` means the bytes matched no known
signature at all; :class:`UnsupportedMimeError` means the type was identified
but no handler exists for it this phase (pdf/docx/xlsx only).
"""

from app.extraction.base import ExtractedDocument, ExtractionHandler
from app.extraction.docx import DocxHandler
from app.extraction.pdf import PdfHandler
from app.extraction.sniff import MIME_DOCX, MIME_PDF, MIME_XLSX, sniff_mime
from app.extraction.xlsx import XlsxHandler


class UnsupportedMimeError(ValueError):
    """Content was identified but has no extraction handler this phase."""


def build_registry() -> dict[str, ExtractionHandler]:
    """Map every supported sniffed mime to a fresh handler instance."""
    return {
        MIME_PDF: PdfHandler(),
        MIME_DOCX: DocxHandler(),
        MIME_XLSX: XlsxHandler(),
    }


def get_handler(mime: str) -> ExtractionHandler:
    """Return the handler registered for ``mime``; raise when unsupported."""
    handler = build_registry().get(mime)
    if handler is None:
        raise UnsupportedMimeError(f"no extraction handler for {mime}")
    return handler


def extract_document(data: bytes) -> ExtractedDocument:
    """Sniff ``data`` then dispatch to the matching handler (#19)."""
    return get_handler(sniff_mime(data)).extract(data)
