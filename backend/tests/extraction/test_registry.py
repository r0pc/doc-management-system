"""Registry dispatch: sniffed mime -> handler; unsupported/unknown taxonomy."""

import pytest

from app.extraction.base import ExtractedDocument, UnknownMimeError
from app.extraction.docx import DocxHandler
from app.extraction.pdf import PdfHandler
from app.extraction.registry import (
    UnsupportedMimeError,
    build_registry,
    extract_document,
    get_handler,
)
from app.extraction.sniff import MIME_DOCX, MIME_PDF, MIME_XLSX, MIME_ZIP
from app.extraction.xlsx import XlsxHandler


def test_registry_maps_exactly_the_supported_mimes() -> None:
    assert set(build_registry()) == {MIME_PDF, MIME_DOCX, MIME_XLSX}


@pytest.mark.parametrize(
    ("mime", "handler_type"),
    [
        (MIME_PDF, PdfHandler),
        (MIME_DOCX, DocxHandler),
        (MIME_XLSX, XlsxHandler),
    ],
)
def test_get_handler_returns_matching_handler_type(mime: str, handler_type: type) -> None:
    assert isinstance(get_handler(mime), handler_type)


@pytest.mark.parametrize("mime", ["text/plain", MIME_ZIP, "image/png"])
def test_get_handler_rejects_known_but_unsupported_mime(mime: str) -> None:
    with pytest.raises(UnsupportedMimeError) as excinfo:
        get_handler(mime)
    assert isinstance(excinfo.value, ValueError)


def test_extract_document_dispatches_pdf(pdf_bytes: bytes) -> None:
    result = extract_document(pdf_bytes)
    assert isinstance(result, ExtractedDocument)
    assert result.mime_sniffed == MIME_PDF
    assert result.ocr_used is False


def test_extract_document_dispatches_docx(docx_bytes: bytes) -> None:
    result = extract_document(docx_bytes)
    assert result.mime_sniffed == MIME_DOCX
    assert "Widgets" in result.text


def test_extract_document_rejects_plain_zip(plain_zip_bytes: bytes) -> None:
    with pytest.raises(UnsupportedMimeError):
        extract_document(plain_zip_bytes)


def test_extract_document_propagates_unknown_mime(garbage_bytes: bytes) -> None:
    with pytest.raises(UnknownMimeError):
        extract_document(garbage_bytes)
