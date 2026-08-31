"""Storage abstraction: the Storage protocol, immutability errors, shared guard.

Invariant #16: primary-bucket objects are never overwritten — an edit is a new
blob plus a new ``document_versions`` row. Both backends enforce this through
:class:`PrimaryBlobGuard` so the semantics cannot drift between local and MinIO.
"""

from __future__ import annotations

import tempfile
from typing import BinaryIO, Final, Protocol

from app.storage.keys import key_kind

PRESIGN_MIN_TTL: Final = 60
PRESIGN_MAX_TTL: Final = 120
_SPOOL_THRESHOLD_BYTES: Final = 8 * 1024 * 1024
_CHUNK_BYTES: Final = 1024 * 1024


class ByteStream(Protocol):
    """Minimal readable byte stream — files, BytesIO and SpooledTemporaryFile
    all satisfy it structurally (BinaryIO excludes SpooledTemporaryFile)."""

    def read(self, size: int = ..., /) -> bytes: ...


def clamp_presign_ttl(ttl: int) -> int:
    """Pin presigned lifetimes to the 60-120s policy window."""
    return max(PRESIGN_MIN_TTL, min(PRESIGN_MAX_TTL, ttl))


class BlobExistsError(Exception):
    """A primary blob already exists at this key with different bytes (#16)."""

    def __init__(self, key: str) -> None:
        super().__init__(f"primary blob already exists with different bytes: {key}")
        self.key = key


class ImmutableKeyError(Exception):
    """Deletion attempted on a primary-bucket key, which is immutable (#16)."""

    def __init__(self, key: str) -> None:
        super().__init__(f"primary-bucket keys are immutable: {key}")
        self.key = key


from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectStat:
    """Metadata about a stored object. Deliberately carries no bytes (#1)."""

    size_bytes: int


class Storage(Protocol):
    """Backend-neutral object storage surface (invariant #15: permission lives
    on the documents row; the object key is never an authorisation boundary)."""

    def stat(self, key: str) -> ObjectStat | None:
        """Size of the object at ``key``, or None if it does not exist.

        Metadata only: the API calls this on the write path, where invariant #1
        forbids reading the body.
        """
        ...

    def put(self, key: str, data: BinaryIO, *, content_type: str) -> str:
        """Store bytes under key; returns the key. Primary keys dedup or reject."""
        ...

    def open(self, key: str, *, byte_range: tuple[int, int] | None = None) -> BinaryIO:
        """Open for reading; byte_range is an inclusive (start, end) window."""
        ...

    def presign(self, key: str, ttl: int, *, filename: str) -> str:
        """Presigned GET download URL; ttl clamped to [60, 120] seconds."""
        ...

    def delete(self, key: str) -> None:
        """Remove a mutable (quarantine/derived) object."""
        ...


def _streams_equal(first: ByteStream, second: ByteStream) -> bool:
    """Chunk-wise byte equality without loading either stream fully."""
    while True:
        left = first.read(_CHUNK_BYTES)
        right = second.read(_CHUNK_BYTES)
        if left != right:
            return False
        if not left:
            return True


class PrimaryBlobGuard:
    """Mixin enforcing #16 identically across backends.

    Hosts must set ``bucket_prefix`` and implement ``_open_existing`` and
    ``_write_object``; ``guarded_put``/``require_mutable`` then give every
    backend uniform put/delete semantics.
    """

    bucket_prefix: str

    def _open_existing(self, key: str) -> BinaryIO | None:
        """Readable handle for an already-stored object, else None."""
        ...

    def _write_object(self, key: str, data: ByteStream, content_type: str) -> None:
        """Persist the already-gated stream. Backend-specific."""
        ...

    def require_mutable(self, key: str) -> None:
        """Raise ImmutableKeyError when key lives in the primary bucket."""
        if key_kind(key, prefix=self.bucket_prefix) == "primary":
            raise ImmutableKeyError(key)

    def guarded_put(self, key: str, data: BinaryIO, *, content_type: str) -> str:
        """Materialise, gate against #16, then write; idempotent on equal bytes.

        The incoming stream is spooled (memory up to 8 MiB, then disk) so both
        the comparison and the write see the full payload even when the caller
        passed a non-seekable stream.
        """
        with tempfile.SpooledTemporaryFile(max_size=_SPOOL_THRESHOLD_BYTES) as spool:
            while chunk := data.read(_CHUNK_BYTES):
                spool.write(chunk)
            spool.seek(0)
            if self._is_existing_duplicate(key, spool):
                return key
            spool.seek(0)
            self._write_object(key, spool, content_type)
        return key

    def _is_existing_duplicate(self, key: str, incoming: ByteStream) -> bool:
        """True when a primary blob exists with byte-identical content (#16).

        Raises BlobExistsError when it exists with different bytes. Non-primary
        kinds are mutable and always return False.
        """
        if key_kind(key, prefix=self.bucket_prefix) != "primary":
            return False
        existing = self._open_existing(key)
        if existing is None:
            return False
        with existing:
            if not _streams_equal(existing, incoming):
                raise BlobExistsError(key)
            return True
