"""DocxHandler: paragraphs plus table cells on a single pseudo-page."""

from app.extraction.base import ExtractedDocument
from app.extraction.docx import DocxHandler
from app.extraction.sniff import MIME_DOCX


def test_extract_paragraphs_and_table_cells(docx_bytes: bytes) -> None:
    result = DocxHandler().extract(docx_bytes)
    assert isinstance(result, ExtractedDocument)
    assert "Invoice summary for vendor engagement." in result.text
    assert "Payment terms follow the ledger schedule." in result.text
    assert "Widgets\t12" in result.text  # table rows survive extraction
    assert result.mime_sniffed == MIME_DOCX
    assert result.char_count == len(result.text)
    assert result.ocr_used is False


def test_single_pseudo_page_numbered_one(docx_bytes: bytes) -> None:
    pages = DocxHandler().extract(docx_bytes).pages
    assert len(pages) == 1
    assert pages[0].page_no == 1
