"""Live MinIO roundtrip. Deselected by default (``-m "not integration"`` addopts)
and additionally skipped unless ``MINIO_TEST_ENDPOINT`` is set.

Run explicitly:  MINIO_TEST_ENDPOINT=localhost:9000 pytest -m integration tests/storage
"""

import io
import os
import uuid

import pytest

from app.storage.keys import quarantine_key
from app.storage.s3 import S3Storage

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("MINIO_TEST_ENDPOINT"),
        reason="MINIO_TEST_ENDPOINT (+ optional credentials) not configured",
    ),
]


def test_minio_put_open_roundtrip() -> None:
    import boto3  # lazy: network-capable import only inside the live test
    from botocore.exceptions import ClientError

    endpoint = os.environ["MINIO_TEST_ENDPOINT"]
    scheme = "https" if os.environ.get("MINIO_TEST_SECURE") else "http"
    client = boto3.client(
        "s3",
        endpoint_url=f"{scheme}://{endpoint}",
        aws_access_key_id=os.environ.get("MINIO_TEST_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.environ.get("MINIO_TEST_SECRET_KEY", "minioadmin"),
        region_name="us-east-1",
    )
    for kind in ("quarantine", "primary", "derived"):
        try:
            client.create_bucket(Bucket=f"docs-{kind}")
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise

    storage = S3Storage(client)
    key = quarantine_key(uuid.uuid4(), uuid.uuid4())
    payload = b"minio-integration-payload"
    assert storage.put(key, io.BytesIO(payload), content_type="text/plain") == key
    handle = storage.open(key)
    try:
        assert handle.read() == payload
    finally:
        handle.close()
