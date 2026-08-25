"""clamd INSTREAM client: exact wire framing, verdict parsing, fail-closed errors."""

import socket
import struct

import pytest

from app.workers.scanning import CLAMAV_HOST, CLAMAV_PORT, ScanError, ScanVerdict, clamd_scan


class FakeSocket:
    """Records every sendall byte; replays one canned clamd response."""

    def __init__(self, response: bytes, *, fail_with: Exception | None = None) -> None:
        self.sent = b""
        self._response = response
        self._fail_with = fail_with

    def sendall(self, data: bytes) -> None:
        if self._fail_with is not None:
            raise self._fail_with
        self.sent += data

    def recv(self, bufsize: int) -> bytes:
        if self._fail_with is not None:
            raise self._fail_with
        replayed, self._response = self._response, b""
        return replayed

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.sent += b""  # closing is a no-op for the double


def _patch_connect(monkeypatch: pytest.MonkeyPatch, sock: FakeSocket) -> list[tuple[object, ...]]:
    calls: list[tuple[object, ...]] = []

    def fake_create_connection(address: tuple[str, int], timeout: float | None) -> FakeSocket:
        calls.append((address, timeout))
        return sock

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    return calls


def test_clean_verdict_parses_stream_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = FakeSocket(b"stream: OK\0")
    _patch_connect(monkeypatch, sock)
    verdict = clamd_scan("127.0.0.1", 3310, b"clean-bytes")
    assert verdict == ScanVerdict(clean=True, signature=None)


def test_infected_verdict_extracts_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = FakeSocket(b"stream: Eicar-Test-Signature FOUND\0")
    _patch_connect(monkeypatch, sock)
    verdict = clamd_scan("127.0.0.1", 3310, b"infected-bytes")
    assert verdict.clean is False
    assert verdict.signature == "Eicar-Test-Signature"


def test_framing_bytes_exact_zinstream_length_prefixed_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"A" * 20_000  # spans three chunks: 8192 + 8192 + 3616
    sock = FakeSocket(b"stream: OK\0")
    calls = _patch_connect(monkeypatch, sock)

    clamd_scan("10.1.2.3", 3310, data, timeout=7.5)

    assert calls == [(("10.1.2.3", 3310), 7.5)]
    expected = b"zINSTREAM\0"
    for start in range(0, len(data), 8192):
        chunk = data[start : start + 8192]
        expected += struct.pack("!I", len(chunk)) + chunk
    expected += struct.pack("!I", 0)  # terminating empty chunk
    assert sock.sent == expected


def test_default_host_port_constants_are_clamav_defaults() -> None:
    assert CLAMAV_HOST == "127.0.0.1"
    assert CLAMAV_PORT == 3310


def test_socket_timeout_raises_scan_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = FakeSocket(b"", fail_with=TimeoutError("timed out"))
    _patch_connect(monkeypatch, sock)
    with pytest.raises(ScanError):
        clamd_scan("127.0.0.1", 3310, b"bytes")


def test_connection_refused_raises_scan_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(address: tuple[str, int], timeout: float | None) -> FakeSocket:
        msg = "connection refused"
        raise OSError(msg)

    monkeypatch.setattr(socket, "create_connection", refused)
    with pytest.raises(ScanError):
        clamd_scan("127.0.0.1", 3310, b"bytes")


def test_malformed_response_raises_scan_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = FakeSocket(b"PROTOCOL ERROR\0")
    _patch_connect(monkeypatch, sock)
    with pytest.raises(ScanError):
        clamd_scan("127.0.0.1", 3310, b"bytes")
