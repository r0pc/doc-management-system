"""Invariant #19: content decides — filenames do not exist anywhere in this API."""

import inspect

import pytest

from app.extraction.base import UnknownMimeError
from app.extraction.registry import extract_document
from app.extraction.sniff import MIME_DOCX, MIME_PDF, MIME_XLSX, MIME_ZIP, sniff_mime


def test_sniff_identifies_generated_pdf(pdf_bytes: bytes) -> None:
    assert sniff_mime(pdf_bytes) == MIME_PDF


def test_sniff_identifies_docx_by_zip_members(docx_bytes: bytes) -> None:
    assert sniff_mime(docx_bytes) == MIME_DOCX


def test_sniff_identifies_xlsx_by_zip_members(xlsx_bytes: bytes) -> None:
    assert sniff_mime(xlsx_bytes) == MIME_XLSX


def test_sniff_plain_zip_falls_back_to_generic(plain_zip_bytes: bytes) -> None:
    assert sniff_mime(plain_zip_bytes) == MIME_ZIP


def test_sniff_ooxml_style_zip_without_office_members_is_generic(
    custom_ooxml_zip_bytes: bytes,
) -> None:
    assert sniff_mime(custom_ooxml_zip_bytes) == MIME_ZIP


def test_sniff_empty_bytes_raise_unknown_mime_error() -> None:
    with pytest.raises(UnknownMimeError):
        sniff_mime(b"")


def test_sniff_unidentifiable_bytes_raise_unknown_mime_error(
    garbage_bytes: bytes,
) -> None:
    with pytest.raises(UnknownMimeError):
        sniff_mime(garbage_bytes)


def test_misnamed_extension_cannot_influence_dispatch(pdf_bytes: bytes) -> None:
    """#19 proof: the payload is a PDF even though the variable claims xlsx.

    There is no filename parameter to poison the result — dispatch runs on
    sniffed content alone.
    """
    xlsx_named_payload = pdf_bytes
    assert sniff_mime(xlsx_named_payload) == MIME_PDF
    extracted = extract_document(xlsx_named_payload)
    assert extracted.mime_sniffed == MIME_PDF


def test_no_filename_parameter_exists_on_public_api() -> None:
    for func in (sniff_mime, extract_document):
        assert "filename" not in inspect.signature(func).parameters

def test_sniff_text_plain(tmp_path) -> None:
    p = tmp_path / "x.txt"
    p.write_bytes(b"Hello world")
    assert sniff_mime(p.read_bytes()) == "text/plain"
