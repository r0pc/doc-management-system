"""Safe inline delivery of stored bytes.

Two problems this module exists to prevent.

**Scriptable content served inline.** A blob is promoted to the primary bucket
during the *scan* stage, before extraction runs, and keeps whatever mime the
sniffer assigned it. An uploaded ``.html`` therefore lands with
``mime_sniffed='text/html'`` even though extraction later fails the document —
and the content routes gate on ``blob_key``, not on status. Served
``Content-Disposition: inline`` with its sniffed type, that HTML executes. The
frontend compounds it by wrapping the response in a ``blob:`` URL, which
inherits the application's origin rather than a null one, so the script runs
with access to the caller's session.

The fix is default-deny: only a small, non-scriptable allowlist is ever served
inline with its own type. Everything else — including anything unrecognised —
is downgraded to ``application/octet-stream`` and forced to ``attachment``.

**Header injection through filenames.** On the dev-storage path the presign
HMAC covers ``METHOD:key:expires`` and *not* the ``filename`` query parameter,
so the filename is attacker-controlled on any otherwise-valid URL. Stripping
only double quotes leaves ``\\r`` and ``\\n`` free to split the header.
"""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import quote

#: Types safe to render inline. Deliberately small and deliberately excludes
#: every XML dialect: `image/svg+xml` carries <script>, and `application/xml`
#: can be served as XHTML by a sniffing browser. Adding to this list means
#: asserting the type cannot execute script in any supported browser.
INLINE_SAFE_MIMES: Final[frozenset[str]] = frozenset(
    {
        "application/pdf",
        "text/plain",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
)

_FALLBACK_MIME: Final[str] = "application/octet-stream"
_FALLBACK_NAME: Final[str] = "download"

#: Conservative token set for the legacy `filename=` parameter. Anything else
#: is dropped there and preserved only in the RFC 5987 `filename*` form.
_SAFE_NAME_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]")


def _sanitise_name(filename: str) -> str:
    """Reduce ``filename`` to a token that cannot alter the header."""
    collapsed = _SAFE_NAME_CHARS.sub("_", filename).strip("._")
    return collapsed or _FALLBACK_NAME


def safe_content_disposition(disposition: str, filename: str) -> str:
    """A ``Content-Disposition`` value that cannot inject headers.

    Emits both the sanitised legacy ``filename=`` for older clients and the
    RFC 5987 ``filename*=UTF-8''`` form so non-ASCII names survive intact.
    """
    ascii_name = _sanitise_name(filename)
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def safe_inline_delivery(mime: str | None, filename: str) -> tuple[str, str]:
    """Return the ``(media_type, content_disposition)`` safe to serve.

    Default-deny: a mime absent from :data:`INLINE_SAFE_MIMES` — including
    ``None`` — is downgraded to ``application/octet-stream`` and forced to
    ``attachment`` so the browser saves it instead of rendering it.
    """
    if mime in INLINE_SAFE_MIMES:
        return mime, safe_content_disposition("inline", filename)
    return _FALLBACK_MIME, safe_content_disposition("attachment", filename)


#: Sent alongside every byte-serving response. `nosniff` stops a browser from
#: second-guessing the declared type and rendering octet-stream as HTML;
#: `sandbox` neuters script and same-origin access even if something scriptable
#: ever slips past the allowlist.
SAFE_CONTENT_HEADERS: Final[dict[str, str]] = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
}
