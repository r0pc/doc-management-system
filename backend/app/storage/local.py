"""Local-filesystem backend for dev/test.

Writes land under ``root_dir/<key>``. Presigning produces HMAC-signed URLs for
a dev-only verification endpoint — **never deploy this backend in production**:
nothing server-side enforces these signatures here, MinIO/S3 replaces it.
"""

import hashlib
import hmac
import io
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Final, assert_never
from urllib.parse import quote

from app.storage.base import ByteStream, PrimaryBlobGuard, clamp_presign_ttl
from app.storage.keys import DEFAULT_BUCKET_PREFIX

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer

DEV_PRESIGN_BASE_URL: Final = "http://localhost:8000/v1/dev-storage/"
_COPY_CHUNK_BYTES: Final = 1024 * 1024


class RangeFile(io.RawIOBase):
    """Read-only raw stream over the inclusive byte window [start, end] of an
    open binary file. Seeks/tells are logical positions within the window."""

    def __init__(self, fp: BinaryIO, start: int, end: int) -> None:
        super().__init__()
        self._fp = fp
        self._start = start
        self._end = end
        self._pos = start
        fp.seek(start)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def readinto(self, b: WriteableBuffer) -> int:
        view = memoryview(b)
        remaining = self._end - self._pos + 1
        if remaining <= 0:
            return 0
        chunk = self._fp.read(min(len(view), remaining))
        if not chunk:
            return 0
        self._pos += len(chunk)
        view[: len(chunk)] = chunk
        return len(chunk)

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        match whence:
            case os.SEEK_SET:
                target = offset
            case os.SEEK_CUR:
                target = self._pos + offset
            case os.SEEK_END:
                target = self._end + 1 + offset
            case other:
                msg = f"invalid whence: {other!r}"
                raise ValueError(msg)
        self._pos = max(self._start, min(target, self._end + 1))
        self._fp.seek(self._pos)
        return self._pos - self._start

    def tell(self) -> int:
        return self._pos - self._start

    def close(self) -> None:
        if not self.closed:
            self._fp.close()
        super().close()


class LocalStorage(PrimaryBlobGuard):
    """Filesystem backend. Dev/test only — presigns are HMAC dev URLs."""

    def __init__(
        self,
        root_dir: Path,
        signing_secret: bytes | str,
        bucket_prefix: str = DEFAULT_BUCKET_PREFIX,
    ) -> None:
        """``signing_secret`` is a DEV-ONLY HMAC key for presigned URLs; it has
        no production counterpart and must never hold a real credential."""
        self.root_dir = root_dir.resolve()
        self.bucket_prefix = bucket_prefix
        match signing_secret:
            case str():
                self._secret = signing_secret.encode("utf-8")
            case bytes():
                self._secret = signing_secret
            case unreachable:
                assert_never(unreachable)

    def _resolve(self, key: str) -> Path:
        """Absolute path for key, refusing anything escaping the root."""
        if "\x00" in key:
            msg = f"key contains NUL byte: {key!r}"
            raise ValueError(msg)
        target = (self.root_dir / key).resolve()
        if not target.is_relative_to(self.root_dir):
            msg = f"key escapes storage root: {key!r}"
            raise ValueError(msg)
        return target

    def put(self, key: str, data: BinaryIO, *, content_type: str) -> str:
        return self.guarded_put(key, data, content_type=content_type)

    def _open_existing(self, key: str) -> BinaryIO | None:
        try:
            return self._resolve(key).open("rb")
        except FileNotFoundError:
            return None

    def _write_object(self, key: str, data: ByteStream, content_type: str) -> None:
        """Atomic write via temp file + replace; ``content_type`` is accepted
        for protocol parity (the filesystem keeps no media-type metadata)."""
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle_fd, temp_name = tempfile.mkstemp(dir=target.parent, suffix=".part")
        temp = Path(temp_name)
        try:
            with os.fdopen(handle_fd, "wb") as out:
                while chunk := data.read(_COPY_CHUNK_BYTES):
                    out.write(chunk)
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink()

    def open(self, key: str, *, byte_range: tuple[int, int] | None = None) -> BinaryIO:
        handle: BinaryIO = self._resolve(key).open("rb")
        if byte_range is None:
            return handle
        start, end = byte_range
        if start < 0 or end < start:
            handle.close()
            msg = f"invalid byte_range: {byte_range!r}"
            raise ValueError(msg)
        return io.BufferedReader(RangeFile(handle, start, end))

    def presign(self, key: str, ttl: int, *, filename: str) -> str:
        """Dev HMAC URL; ``filename`` accepted for protocol parity only."""
        expires = int(time.time()) + clamp_presign_ttl(ttl)
        signature = hmac.new(self._secret, f"{key}:{expires}".encode(), hashlib.sha256).hexdigest()
        return f"{DEV_PRESIGN_BASE_URL}{quote(key, safe='')}?expires={expires}&sig={signature}"

    def verify_presign(self, key: str, expires: int, sig: str, now: float | None = None) -> bool:
        """Constant-time check of a dev presign; False once expired."""
        current = time.time() if now is None else now
        if expires <= current:
            return False
        expected = hmac.new(
            self._secret, f"{key}:{int(expires)}".encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig)

    def delete(self, key: str) -> None:
        self.require_mutable(key)
        self._resolve(key).unlink()
