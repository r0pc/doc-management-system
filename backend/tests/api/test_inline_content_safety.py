"""Inline serving must never hand the browser something scriptable.

A blob promoted during the scan stage keeps whatever mime the sniffer gave it,
even when extraction later fails — so `text/html` and `image/svg+xml` blobs do
reach the content routes. Served `inline` with their sniffed type they execute,
and the frontend wraps the response in a `blob:` URL, which inherits the app's
origin. That is stored XSS with access to the caller's session.

Filenames are attacker-controlled on the dev-storage path: the presign HMAC
covers METHOD:key:expires and NOT the filename query parameter.
"""

from __future__ import annotations

import pytest

from app.api.v1.content_safety import (
    INLINE_SAFE_MIMES,
    safe_content_disposition,
    safe_inline_delivery,
)

SCRIPTABLE = [
    "text/html",
    "image/svg+xml",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
    "application/javascript",
    "text/javascript",
    "application/rdf+xml",
]


@pytest.mark.parametrize("mime", SCRIPTABLE)
def test_scriptable_mimes_are_forced_to_attachment_octet_stream(mime: str) -> None:
    media_type, disposition = safe_inline_delivery(mime, "evil.html")
    assert media_type == "application/octet-stream"
    assert disposition.startswith("attachment;")


@pytest.mark.parametrize("mime", ["application/pdf", "text/plain", "image/png", "image/jpeg"])
def test_known_safe_mimes_stay_inline_with_their_type(mime: str) -> None:
    media_type, disposition = safe_inline_delivery(mime, "report.pdf")
    assert media_type == mime
    assert disposition.startswith("inline;")


def test_unknown_mime_is_not_trusted_inline() -> None:
    """Default-deny: anything not on the allowlist is downloaded, not rendered."""
    media_type, disposition = safe_inline_delivery("application/x-shockwave-flash", "x.swf")
    assert media_type == "application/octet-stream"
    assert disposition.startswith("attachment;")


def test_missing_mime_is_not_trusted_inline() -> None:
    media_type, disposition = safe_inline_delivery(None, "unknown.bin")
    assert media_type == "application/octet-stream"
    assert disposition.startswith("attachment;")


def test_allowlist_contains_nothing_scriptable() -> None:
    for mime in INLINE_SAFE_MIMES:
        assert "html" not in mime
        assert "javascript" not in mime
        assert not mime.endswith("+xml")
        assert mime != "application/xml"


@pytest.mark.parametrize(
    "raw",
    [
        'a"b.pdf',
        "a\r\nX-Injected: 1.pdf",
        "a\nSet-Cookie: sid=1.pdf",
        "a;b.pdf",
        "a\rb.pdf",
    ],
    ids=["quote", "crlf", "lf", "semicolon", "cr"],
)
def test_header_injection_characters_never_reach_the_header(raw: str) -> None:
    _, disposition = safe_inline_delivery("application/pdf", raw)
    # CR/LF are what actually split a header, so their absence is the property
    # that matters. A sanitised token appearing INSIDE a quoted value is inert.
    assert "\r" not in disposition
    assert "\n" not in disposition
    # Exactly two quotes: the delimiters of the legacy filename= value. More
    # would mean the value broke out of its own quoted-string.
    assert disposition.count('"') == 2
    legacy = disposition.split('"')[1]
    assert ";" not in legacy


def test_non_ascii_filename_is_rfc5987_encoded_not_dropped() -> None:
    _, disposition = safe_inline_delivery("application/pdf", "reporte-año.pdf")
    assert "filename*=UTF-8''" in disposition
    assert "%C3%B1" in disposition or "%c3%b1" in disposition


def test_a_filename_with_no_safe_characters_still_yields_a_usable_name() -> None:
    _, disposition = safe_inline_delivery("application/pdf", "///")
    assert "filename=" in disposition
    assert '""' not in disposition


def test_disposition_helper_is_reusable_for_attachments() -> None:
    disposition = safe_content_disposition("attachment", "a\r\nb.pdf")
    assert disposition.startswith("attachment;")
    assert "\r" not in disposition and "\n" not in disposition
