"""PdfHandler: page collection, thin-text-layer OCR handoff, probe helper."""

import pytest

from app.extraction.base import ExtractedDocument, NeedsOcrError
from app.extraction.pdf import PdfHandler, has_text_layer


def test_extract_returns_joined_pages(pdf_bytes: bytes) -> None:
    result = PdfHandler().extract(pdf_bytes)
    assert isinstance(result, ExtractedDocument)
    assert result.text == "\n\n".join(page.text for page in result.pages)
    assert result.char_count == len(result.text)
    assert result.mime_sniffed == "application/pdf"
    assert result.ocr_used is False


def test_pages_are_numbered_from_one(pdf_bytes: bytes) -> None:
    result = PdfHandler().extract(pdf_bytes)
    assert [page.page_no for page in result.pages] == [1, 2]
    assert "Quarterly report" in result.pages[0].text
    assert "Second page" in result.pages[1].text


def test_scanned_pdf_raises_needs_ocr_error(scanned_pdf_bytes: bytes) -> None:
    with pytest.raises(NeedsOcrError):
        PdfHandler().extract(scanned_pdf_bytes)


def test_has_text_layer_true_for_text_pdf(pdf_bytes: bytes) -> None:
    assert has_text_layer(pdf_bytes) is True


def test_has_text_layer_false_for_scanned_pdf(scanned_pdf_bytes: bytes) -> None:
    assert has_text_layer(scanned_pdf_bytes) is False
