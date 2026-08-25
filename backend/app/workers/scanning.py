"""Raw clamd INSTREAM client over a plain socket — no clamd-client dependency.

Protocol (clamd INSTREAM): the client sends ``zINSTREAM\0``, then a sequence of
``struct.pack("!I", len(chunk)) + chunk`` frames (8192-byte chunks here), then
one zero-length frame. clamd replies ``stream: OK\0`` for clean content or
``stream: <signature> FOUND\0`` for a detection. Anything else — malformed
reply, socket error, timeout — raises :class:`ScanError`: scanning fails
CLOSED, an unreadable verdict is never treated as clean.

TODO(env-config-phase2): host/port live as module constants because
``app/config.py`` is frozen this wave; they move to Settings fields when the
config wave reopens (alongside a storage-root field).
"""

import socket
import struct
from dataclasses import dataclass
from typing import Final

CLAMAV_HOST: Final = "127.0.0.1"
CLAMAV_PORT: Final = 3310

_HANDSHAKE: Final = b"zINSTREAM\0"
_CHUNK_BYTES: Final = 8192
_MAX_RESPONSE_BYTES: Final = 64 * 1024
_OK_SUFFIX: Final = "OK"
_FOUND_SUFFIX: Final = "FOUND"
_STREAM_PREFIX: Final = "stream: "


class ScanError(Exception):
    """clamd was unreachable, timed out, or answered unintelligibly."""


@dataclass(frozen=True, slots=True)
class ScanVerdict:
    """Outcome of one INSTREAM scan; ``signature`` is set only when infected."""

    clean: bool
    signature: str | None


def _recv_response(conn: socket.socket) -> str:
    """Read one NUL-terminated clamd reply, capped to a sane size."""
    buffer = b""
    while b"\0" not in buffer:
        if len(buffer) > _MAX_RESPONSE_BYTES:
            msg = "clamd response exceeded size cap without terminator"
            raise ScanError(msg)
        received = conn.recv(_CHUNK_BYTES)
        if not received:
            msg = "clamd closed the connection before a full reply"
            raise ScanError(msg)
        buffer += received
    return buffer.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def _parse_verdict(response: str) -> ScanVerdict:
    """Map a clamd reply line to a verdict; unknown shapes fail closed."""
    if response == f"{_STREAM_PREFIX}{_OK_SUFFIX}":
        return ScanVerdict(clean=True, signature=None)
    if response.startswith(_STREAM_PREFIX) and response.endswith(f" {_FOUND_SUFFIX}"):
        signature = response[len(_STREAM_PREFIX) : -len(_FOUND_SUFFIX) - 1]
        return ScanVerdict(clean=False, signature=signature)
    msg = f"unrecognised clamd response: {response!r}"
    raise ScanError(msg)


def clamd_scan(host: str, port: int, data: bytes, timeout: float = 30.0) -> ScanVerdict:
    """Scan ``data`` against clamd's INSTREAM port; fail closed on any fault."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as conn:
            conn.sendall(_HANDSHAKE)
            for start in range(0, len(data), _CHUNK_BYTES):
                chunk = data[start : start + _CHUNK_BYTES]
                conn.sendall(struct.pack("!I", len(chunk)) + chunk)
            conn.sendall(struct.pack("!I", 0))
            return _parse_verdict(_recv_response(conn))
    except ScanError:
        raise
    except OSError as exc:
        msg = f"clamd INSTREAM exchange failed: {type(exc).__name__}"
        raise ScanError(msg) from exc
