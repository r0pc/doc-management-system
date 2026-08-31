"""Wire-contract tests for the MinIO/S3 backend against a dict-backed fake client."""

import hashlib
import io
import uuid

import pytest

from app.storage.base import BlobExistsError, ImmutableKeyError
from app.storage.keys import DEFAULT_BUCKET_PREFIX, bucket_name, primary_key, quarantine_key

TENANT_ID = uuid.UUID(int=1)
UPLOAD_ID = uuid.UUID(int=2)
SHA_A = hashlib.sha256(b"document-a").hexdigest()
SHA_B = hashlib.sha256(b"document-b").hexdigest()


def test_put_quarantine_targets_kind_bucket_with_content_type(s3_storage, fake_s3):
    key = quarantine_key(TENANT_ID, UPLOAD_ID)
    s3_storage.put(key, io.BytesIO(b"scan me"), content_type="application/pdf")
    puts = fake_s3.calls_to("put_object")
    assert len(puts) == 1
    assert puts[0]["Bucket"] == "docs-quarantine"
    assert puts[0]["Key"] == key
    assert puts[0]["ContentType"] == "application/pdf"


def test_put_primary_when_absent_heads_then_writes(s3_storage, fake_s3):
    key = primary_key(TENANT_ID, SHA_A)
    s3_storage.put(key, io.BytesIO(b"first"), content_type="application/pdf")
    assert len(fake_s3.calls_to("head_object")) == 1
    assert len(fake_s3.calls_to("put_object")) == 1


def test_put_primary_with_different_bytes_raises_and_never_writes(s3_storage, fake_s3):
    key = primary_key(TENANT_ID, SHA_A)
    s3_storage.put(key, io.BytesIO(b"original"), content_type="application/pdf")
    with pytest.raises(BlobExistsError):
        s3_storage.put(key, io.BytesIO(b"different"), content_type="application/pdf")
    assert len(fake_s3.calls_to("put_object")) == 1  # only the first put wrote
    with s3_storage.open(key) as handle:
        assert handle.read() == b"original"


def test_put_primary_with_identical_bytes_dedups_without_second_write(s3_storage, fake_s3):
    key = primary_key(TENANT_ID, SHA_A)
    s3_storage.put(key, io.BytesIO(b"identical"), content_type="application/pdf")
    assert s3_storage.put(key, io.BytesIO(b"identical"), content_type="application/pdf") == key
    assert len(fake_s3.calls_to("put_object")) == 1
    with s3_storage.open(key) as handle:
        assert handle.read() == b"identical"


def test_open_without_range_reads_full_body(s3_storage, fake_s3):
    key = quarantine_key(TENANT_ID, UPLOAD_ID)
    s3_storage.put(key, io.BytesIO(b"full body"), content_type="text/plain")
    with s3_storage.open(key) as handle:
        assert handle.read() == b"full body"
    gets = fake_s3.calls_to("get_object")
    assert len(gets) == 1
    assert gets[0]["Range"] is None


def test_open_with_range_sends_inclusive_header(s3_storage, fake_s3):
    bucket = bucket_name("primary", prefix=DEFAULT_BUCKET_PREFIX)
    key = primary_key(TENANT_ID, SHA_A)
    fake_s3.seed(bucket, key, b"0123456789")
    with s3_storage.open(key, byte_range=(3, 5)) as handle:
        assert handle.read() == b"345"
    assert fake_s3.calls_to("get_object")[0]["Range"] == "bytes=3-5"


def test_presign_get_pins_disposition_and_clamps_high_ttl(s3_storage, fake_s3):
    key = primary_key(TENANT_ID, SHA_A)
    url = s3_storage.presign(key, ttl=3600, filename="report.pdf")
    call = fake_s3.calls_to("generate_presigned_url")[0]
    assert call["ClientMethod"] == "get_object"
    assert call["ExpiresIn"] == 120  # clamped down from 3600
    params = call["Params"]
    assert isinstance(params, dict)
    assert params["ResponseContentDisposition"] == 'attachment; filename="report.pdf"'
    assert params["Bucket"] == "docs-primary"
    assert params["Key"] == key
    assert url.startswith("https://fake.s3.local/")


def test_presign_get_clamps_low_ttl_upward(s3_storage, fake_s3):
    key = quarantine_key(TENANT_ID, UPLOAD_ID)
    s3_storage.presign(key, ttl=10, filename="d.pdf")
    assert fake_s3.calls_to("generate_presigned_url")[0]["ExpiresIn"] == 60


def test_presign_put_records_content_type_and_respects_window(s3_storage, fake_s3):
    key = quarantine_key(TENANT_ID, UPLOAD_ID)
    url = s3_storage.presign_put(key, ttl=90, content_type="application/pdf", max_bytes=1024)
    # The client method receives the clamped ttl
    call = fake_s3.calls_to("generate_presigned_post")[0]
    assert call["ExpiresIn"] == 90
    assert call["Bucket"] == bucket_name("quarantine")
    assert call["Key"] == key
    fields = call["Fields"]
    assert isinstance(fields, dict)
    assert fields["Content-Type"] == "application/pdf"
    assert url.url.startswith("https://fake.s3.local/")


def test_delete_primary_raises_without_touching_client(s3_storage, fake_s3):
    with pytest.raises(ImmutableKeyError):
        s3_storage.delete(primary_key(TENANT_ID, SHA_B))
    assert fake_s3.calls == []  # guard fires before ANY client call


def test_delete_quarantine_targets_kind_bucket(s3_storage, fake_s3):
    key = quarantine_key(TENANT_ID, UPLOAD_ID)
    s3_storage.delete(key)
    assert fake_s3.calls_to("delete_object") == [{"Bucket": "docs-quarantine", "Key": key}]
