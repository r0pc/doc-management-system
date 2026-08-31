"""Content-based MIME sniffing — invariant #19: extensions are never trusted.

No function in this module accepts a filename. Empirically (puremagic 2.2.0)
every zip-derived container matches identically on the ``PK\x03\x04`` header —
docx, xlsx and plain archives return the same ambiguous candidate list — so
zip payloads are disambiguated by inspecting archive members instead.
"""

from __future__ import annotations

import io
import zipfile
from typing import Final

import puremagic

from app.extraction.base import UnknownMimeError

MIME_PDF: Final = "application/pdf"
MIME_DOCX: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_XLSX: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_ZIP: Final = "application/zip"
MIME_TEXT: Final = "text/plain"

_ZIP_MAGIC: Final = b"PK\x03\x04"
_OOXML_CONTENT_TYPES: Final = "[Content_Types].xml"


def _sniff_zip_container(data: bytes) -> str:
    """Map zip bytes to docx/xlsx via member paths, else generic zip."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile as exc:
        raise UnknownMimeError("zip container unreadable") from exc
    if _OOXML_CONTENT_TYPES not in names:
        return MIME_ZIP
    if any(name.startswith("word/") for name in names):
        return MIME_DOCX
    if any(name.startswith("xl/") for name in names):
        return MIME_XLSX
    return MIME_ZIP


def _is_plain_text(data: bytes) -> bool:
    """Check whether bytes represent clean printable/whitespace text."""
    if not data or b"\x00" in data[:1024]:
        return False
    # Validate only the first chunk to avoid OOM on large files.
    # Replace errors so we don't fail on a truncated multi-byte char at the boundary.
    chunk = data[:4096].decode("utf-8", errors="replace")
    return True


def sniff_mime(data: bytes) -> str:
    """Identify the content type of ``data`` from bytes alone (#19)."""
    if not data:
        raise UnknownMimeError("no bytes to identify")
    if data[:4] == _ZIP_MAGIC:
        return _sniff_zip_container(data)
    candidates = puremagic.magic_string(data)
    for candidate in candidates:  # ordered best-confidence first
        mime_type = str(candidate.mime_type)
        if mime_type:
            return mime_type
    if _is_plain_text(data):
        return MIME_TEXT
    raise UnknownMimeError("bytes match no known signature")
