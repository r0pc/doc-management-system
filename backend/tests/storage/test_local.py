"""Behavioural tests for the local filesystem backend."""

import hashlib
import hmac
import io
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from app.storage.base import BlobExistsError, ImmutableKeyError
from app.storage.keys import derived_key, primary_key, quarantine_key

TENANT_ID = uuid.UUID(int=1)
UPLOAD_ID = uuid.UUID(int=2)
SHA_A = hashlib.sha256(b"document-a").hexdigest()
SHA_B = hashlib.sha256(b"document-b").hexdigest()
FIXED_NOW = 1_700_000_000.0


def _freeze_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.storage.local.time.time", lambda: FIXED_NOW)


def test_put_then_open_roundtrips_full_object(local_storage):
    key = quarantine_key(TENANT_ID, UPLOAD_ID)
    returned = local_storage.put(key, io.BytesIO(b"hello blob"), content_type="text/plain")
    assert returned == key
    with local_storage.open(key) as handle:
        assert handle.read() == b"hello blob"


def test_open_byte_range_returns_middle_slice(local_storage):
    key = quarantine_key(TENANT_ID, UPLOAD_ID)
    local_storage.put(key, io.BytesIO(b"0123456789"), content_type="text/plain")
    with local_storage.open(key, byte_range=(3, 5)) as handle:
        assert handle.read() == b"345"


def test_open_byte_range_covering_whole_object_returns_everything(local_storage):
    key = quarantine_key(TENANT_ID, UPLOAD_ID)
    local_storage.put(key, io.BytesIO(b"0123456789"), content_type="text/plain")
    with local_storage.open(key, byte_range=(0, 9)) as handle:
        assert handle.read() == b"0123456789"


def test_put_rejects_key_that_escapes_root(local_storage):
    with pytest.raises(ValueError, match="escapes"):
        local_storage.put("../evil", io.BytesIO(b"x"), content_type="text/plain")


def test_open_rejects_nested_traversal_key(local_storage):
    with pytest.raises(ValueError, match="escapes"):
        local_storage.open("docs-quarantine/../../evil")


def test_put_primary_with_different_bytes_raises_blob_exists(local_storage):
    key = primary_key(TENANT_ID, SHA_A)
    local_storage.put(key, io.BytesIO(b"original"), content_type="application/pdf")
    with pytest.raises(BlobExistsError):
        local_storage.put(key, io.BytesIO(b"tampered"), content_type="application/pdf")
    with local_storage.open(key) as handle:
        assert handle.read() == b"original"


def test_put_primary_with_identical_bytes_dedups_silently(local_storage):
    key = primary_key(TENANT_ID, SHA_A)
    local_storage.put(key, io.BytesIO(b"same"), content_type="application/pdf")
    assert local_storage.put(key, io.BytesIO(b"same"), content_type="application/pdf") == key


def test_put_quarantine_overwrites_existing_bytes(local_storage):
    key = quarantine_key(TENANT_ID, UPLOAD_ID)
    local_storage.put(key, io.BytesIO(b"v1"), content_type="text/plain")
    local_storage.put(key, io.BytesIO(b"v2"), content_type="text/plain")
    with local_storage.open(key) as handle:
        assert handle.read() == b"v2"


def test_delete_primary_raises_even_when_object_missing(local_storage):
    with pytest.raises(ImmutableKeyError):
        local_storage.delete(primary_key(TENANT_ID, SHA_B))


def test_delete_quarantine_removes_object_then_missing_raises(local_storage):
    key = quarantine_key(TENANT_ID, UPLOAD_ID)
    local_storage.put(key, io.BytesIO(b"temp"), content_type="text/plain")
    local_storage.delete(key)
    with pytest.raises(FileNotFoundError):
        local_storage.delete(key)


def test_open_missing_key_raises_file_not_found(local_storage):
    with pytest.raises(FileNotFoundError):
        local_storage.open(quarantine_key(TENANT_ID, UPLOAD_ID))


def test_presign_clamps_high_ttl_and_signs_key_and_expiry(local_storage, local_secret, monkeypatch):
    _freeze_clock(monkeypatch)
    key = primary_key(TENANT_ID, SHA_A)
    url = local_storage.presign(key, ttl=3600, filename="doc.pdf")
    assert url.startswith("http://localhost:8000/v1/dev-storage/")
    assert unquote(urlsplit(url).path.removeprefix("/v1/dev-storage/")) == key
    query = parse_qs(urlsplit(url).query)
    expires = int(query["expires"][0])
    assert expires == int(FIXED_NOW) + 120  # clamped down from 3600
    expected_sig = hmac.new(local_secret, f"{key}:{expires}".encode(), hashlib.sha256).hexdigest()
    assert query["sig"][0] == expected_sig


def test_presign_clamps_low_ttl_upward(local_storage, monkeypatch):
    _freeze_clock(monkeypatch)
    url = local_storage.presign(quarantine_key(TENANT_ID, UPLOAD_ID), ttl=10, filename="d.pdf")
    expires = int(parse_qs(urlsplit(url).query)["expires"][0])
    assert expires == int(FIXED_NOW) + 60


def test_verify_presign_accepts_valid_and_rejects_tampered(
    local_storage, local_secret, monkeypatch
):
    _freeze_clock(monkeypatch)
    key = derived_key(SHA_A, "text.txt")
    url = local_storage.presign(key, ttl=90, filename="t.txt")
    query = parse_qs(urlsplit(url).query)
    expires, sig = int(query["expires"][0]), query["sig"][0]
    assert local_storage.verify_presign(key, expires, sig) is True
    assert local_storage.verify_presign(key, expires, "0" * 64) is False
    wrong_key_sig = hmac.new(local_secret, f"other:{expires}".encode(), hashlib.sha256).hexdigest()
    assert local_storage.verify_presign(key, expires, wrong_key_sig) is False


def test_verify_presign_rejects_expired_signature(local_storage, monkeypatch):
    _freeze_clock(monkeypatch)
    key = quarantine_key(TENANT_ID, UPLOAD_ID)
    url = local_storage.presign(key, ttl=60, filename="d.bin")
    query = parse_qs(urlsplit(url).query)
    expires, sig = int(query["expires"][0]), query["sig"][0]
    assert local_storage.verify_presign(key, expires, sig, now=FIXED_NOW + 59) is True
    assert local_storage.verify_presign(key, expires, sig, now=FIXED_NOW + 61) is False
