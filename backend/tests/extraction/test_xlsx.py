"""XlsxHandler: sheet/cell sweep, None-cell skipping, empty-workbook behaviour."""

from app.extraction.base import ExtractedDocument
from app.extraction.sniff import MIME_XLSX
from app.extraction.xlsx import XlsxHandler


def test_extract_cells_across_sheets_skipping_none(xlsx_bytes: bytes) -> None:
    result = XlsxHandler().extract(xlsx_bytes)
    assert isinstance(result, ExtractedDocument)
    lines = result.text.split("\n")
    assert "Total" in lines
    assert "42" in lines  # numeric cells are stringified
    assert "partial" in lines
    assert "audit note" in lines  # second sheet included
    assert "" not in lines  # None cells never become blank lines
    assert result.mime_sniffed == MIME_XLSX
    assert result.char_count == len(result.text)


def test_empty_workbook_returns_empty_extraction_not_ocr(empty_xlsx_bytes: bytes) -> None:
    result = XlsxHandler().extract(empty_xlsx_bytes)
    assert isinstance(result, ExtractedDocument)
    assert result.text == ""
    assert result.char_count == 0
    assert result.ocr_used is False
