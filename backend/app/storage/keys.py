"""Content-addressed object-key builders. Pure string functions, no I/O.

Keys embed the bucket-kind prefix (e.g. ``docs-primary/...``) so one key string
identifies both the kind bucket (:func:`bucket_name`) and the object path.
sha256 digests are validated as 64 *lowercase* hex chars — the canonical form
produced by ``hashlib.hexdigest()`` — so identical content always maps to an
identical key (dedup precondition for invariant #16 / idempotency #5).
"""

from __future__ import annotations

import re
import uuid
from typing import Final, Literal

DEFAULT_BUCKET_PREFIX: Final = "docs-"

KeyKind = Literal["quarantine", "primary", "derived"]

_KINDS: Final = ("quarantine", "primary", "derived")
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")


def _canonical_sha256(digest: str) -> str:
    if _SHA256_PATTERN.fullmatch(digest) is None:
        msg = f"sha256 must be 64 lowercase hex chars, got {digest!r}"
        raise ValueError(msg)
    return digest


def quarantine_key(
    tenant_id: uuid.UUID, upload_id: uuid.UUID, *, prefix: str = DEFAULT_BUCKET_PREFIX
) -> str:
    """Quarantine landing key for an in-flight upload."""
    return f"{prefix}quarantine/{tenant_id}/{upload_id}"


def primary_key(tenant_id: uuid.UUID, sha256: str, *, prefix: str = DEFAULT_BUCKET_PREFIX) -> str:
    """Content-addressed primary key, sharded by the first two hex chars."""
    digest = _canonical_sha256(sha256)
    return f"{prefix}primary/{tenant_id}/{digest[:2]}/{digest}"


def derived_key(sha256: str, name: str, *, prefix: str = DEFAULT_BUCKET_PREFIX) -> str:
    """Derived-artifact key (extracted text, embeddings, indexes)."""
    digest = _canonical_sha256(sha256)
    return f"{prefix}derived/{digest}/{name}"


def bucket_name(kind: KeyKind, *, prefix: str = DEFAULT_BUCKET_PREFIX) -> str:
    """Per-kind bucket name, e.g. ``docs-primary``."""
    return f"{prefix}{kind}"


def key_kind(key: str, *, prefix: str = DEFAULT_BUCKET_PREFIX) -> KeyKind | None:
    """Classify a key by its kind segment; None when the prefix is foreign."""
    for kind in _KINDS:
        if key.startswith(f"{prefix}{kind}/"):
            return kind
    return None
